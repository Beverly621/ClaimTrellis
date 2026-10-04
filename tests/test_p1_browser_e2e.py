"""Real Chromium + real HTTP/PG; Supabase and Jev are explicit test doubles."""

import json
import socket
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from test_postgres_store import pg_url
from test_typesafe_jev import response_body

from claim_trellis.api import create_app
from claim_trellis.config import Settings
from claim_trellis.postgres_store import PostgresAuditStore
from claim_trellis.providers.typesafe_jev import QUESTIONS, TypeSafeJevProvider
from experiments.acceptance.fixtures import EDITED_CLAIM, manuscript, source_text
from experiments.acceptance.trace import verify_trace

__all__ = ["pg_url"]
pytestmark = pytest.mark.browser

# Optional test dependency, installed explicitly in CI. Never affects production.
playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def server(pg_url):
    users = {"token-a": str(uuid4()), "token-b": str(uuid4())}
    settings = Settings(
        database_url=pg_url,
        auth_mode="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="public-test-key",
        jev_api_key="test-only-not-real",
        hosted_provider_enabled=True,
        ip_hash_secret=str(uuid4()),
        paper_daily_user_limit=10,
        paper_run_provider_limit=10,
        paper_max_concurrent_provider_calls=10,
        account_access_enabled=True,
    )
    app = create_app(settings)
    # Only the disposable test pool uses non-TLS localhost; production stays TLS.
    pool = PostgresAuditStore(pg_url, sslmode="disable").pool
    app.state.store.pool = pool
    app.state.paper_workflow_store.pool = pool
    app.state.usage_guard.pool = pool
    app.state.account_profiles.pool = pool

    def auth(request):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in users:
            return httpx.Response(401, json={"message": "invalid test token"})
        return httpx.Response(200, json={"id": users[token], "is_anonymous": True})

    payloads = []

    def jev(request):
        body = json.loads(request.content)
        assert body["model"] == "jev-1.13.0" and set(body["questions"]) == set(QUESTIONS)
        payloads.append(body)
        return httpx.Response(200, json=response_body())

    app.state.auth_transport = httpx.MockTransport(auth)
    app.state.judgment_provider = TypeSafeJevProvider(
        api_key="test-only-not-real",
        endpoint="https://api.typesafe.ai/v1/systemone",
        model="jev-1.13.0",
        transport=httpx.MockTransport(jev),
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    service = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=service.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    try:
        while not service.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                pytest.fail("Disposable test service failed to start.")
            time.sleep(0.02)
        yield url, users, payloads
    finally:
        service.should_exit = True
        thread.join(timeout=15)
        sock.close()
        assert not thread.is_alive()


def sdk_stub(users, token="token-a"):
    return """(() => {
      const users = USERS;
      if (!localStorage.getItem('e2e-initialized')) {
        localStorage.setItem('e2e-token', TOKEN); localStorage.setItem('e2e-initialized','1');
      }
      const listeners = [];
      const user = () => { const t=localStorage.getItem('e2e-token'); return t ? {id:users[t],is_anonymous:true} : null; };
      const session = () => user() ? {access_token:localStorage.getItem('e2e-token'),user:user()} : null;
      const auth = {
        getSession:async()=>({data:{session:session()},error:null}),
        getUser:async()=>({data:{user:user()},error:null}),
        refreshSession:async()=>({data:{session:session()},error:null}),
        onAuthStateChange:f=>{listeners.push(f);return {data:{subscription:{unsubscribe(){}}}};},
        signOut:async()=>{localStorage.removeItem('e2e-token');listeners.forEach(f=>f('SIGNED_OUT',null));return {error:null};},
        signInAnonymously:async()=>{localStorage.setItem('e2e-token', TOKEN);listeners.forEach(f=>f('SIGNED_IN',session()));return {data:{session:session(),user:user()},error:null};}
      };
      window.supabase={createClient:()=>({auth})};
    })();""".replace("USERS", json.dumps(users)).replace("TOKEN", json.dumps(token))


def wait_idle(page):
    playwright.expect(page.locator("#paper-content")).to_have_attribute("aria-busy", "false")


def save_form(page, form, button):
    form.locator('[name="reviewer"]').fill("Synthetic test reviewer")
    form.locator('[name="notes"]').fill(
        "Checked fictional exact spans and source identity for engineering acceptance."
    )
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/decisions")
    ) as response:
        form.get_by_role("button", name=button, exact=True).click()
    assert response.value.status == 200
    wait_idle(page)


def trace_for(client, base, row):
    def get(path):
        response = client.get(path)
        assert response.status_code == 200, response.text
        return response.json()

    manuscripts = get(base + "/manuscripts")
    m = next(m for m in manuscripts if m["manuscript_id"] == row["manuscript_id"])
    c = next(
        c
        for c in get(base + f"/manuscripts/{m['manuscript_id']}/candidates")
        if c["candidate_id"] == row["candidate_id"]
    )
    ref = next(
        r
        for r in get(base + f"/manuscripts/{m['manuscript_id']}/references")
        if r["reference_id"] == row["reference_id"]
    )
    run = get(base + f"/audit-runs/{row['run_id']}")
    item = next(i for i in run["items"] if i["item_id"] == row["item_id"])
    audit_path = f"/api/v1/audits/{row['audit_id']}"
    return dict(
        row=row,
        manuscript=m,
        candidate=c,
        reference=ref,
        source=get(base + f"/sources/{row['source_document_id']}"),
        item=item,
        project_events=get(base + "/events"),
        audit=get(audit_path),
        proposals=get(audit_path + "/proposals"),
        audit_events=get(audit_path + "/events"),
        revisions=get(audit_path + "/revisions"),
    )


@pytest.mark.parametrize("style", ["numeric", "author-year"])
def test_full_browser_workflow_and_traceability(server, style):
    url, users, payloads = server
    with (
        playwright.sync_playwright() as p,
        httpx.Client(base_url=url, headers={"Authorization": "Bearer token-a"}) as client,
    ):
        browser = p.chromium.launch()
        context = browser.new_context()
        context.add_init_script(sdk_stub(users))
        # Never contact a real authentication service or load external SDK in this test.
        context.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/projects")
        page.locator("#project-name").fill(f"P1.7 {style} engineering acceptance")
        page.get_by_role("button", name="Create project", exact=True).click()
        playwright.expect(page.locator('[data-task="manuscript"]')).to_be_visible()
        base = "/api/v1/projects/" + page.url.split("project=")[1]
        form = page.locator('[data-task="manuscript"]')
        form.locator('[name="file"]').set_input_files(
            {"name": f"{style}.txt", "mimeType": "text/plain", "buffer": manuscript(style).encode()}
        )
        form.get_by_role("button", name="Upload manuscript", exact=True).click()
        wait_idle(page)
        page.get_by_role("button", name="Extract exact-span candidates", exact=True).click()
        wait_idle(page)
        candidates = page.locator('[data-task="claim"]')
        assert candidates.count() == 4
        ids = [candidates.nth(i).get_attribute("data-id") for i in range(4)]
        for i, cid in enumerate(ids):
            form = page.locator(f'[data-task="claim"][data-id="{cid}"]')
            if i == 0:
                form.locator('[name="claim"]').fill(EDITED_CLAIM)
            if i != 2:
                for name in ("atomic", "faithful", "necessary_context"):
                    form.locator(f'[name="{name}"]').check()
            save_form(page, form, "Reject candidate" if i == 2 else "Confirm / save edit")
        page.get_by_role("button", name="Parse references", exact=True).click()
        wait_idle(page)
        for title, doi, name in [
            ("Fictional blood pressure study", "10.1234/fictional-a", "a.txt"),
            ("Fictional replication study", "10.1234/fictional-b", "b.txt"),
            ("Wrong source with copied metadata", "10.1234/fictional-a", "wrong.txt"),
        ]:
            form = page.locator('[data-task="source"]')
            text = (
                source_text()
                if name != "wrong.txt"
                else "This deliberately wrong fictional source must be rejected."
            )
            form.locator('[name="file"]').set_input_files(
                {"name": name, "mimeType": "text/plain", "buffer": text.encode()}
            )
            form.locator('[name="title"]').fill(title)
            form.locator('[name="doi"]').fill(doi)
            form.locator('[name="year"]').fill("2024")
            form.locator('[name="tier"]').select_option("full_text")
            form.get_by_role("button", name="Upload source", exact=True).click()
            wait_idle(page)
        page.get_by_role(
            "button", name="Suggest mappings for confirmed claims (not confirmation)", exact=True
        ).click()
        wait_idle(page)
        suggestions = client.get(base + "/source-links").json()
        sources = client.get(base + "/sources").json()
        filenames = {s["source_document_id"]: s["filename"] for s in sources}
        assert len(suggestions) == 6  # ambiguous metadata, multi-source, unmapped citation
        for link in suggestions:
            if link["source_document_id"] is None:
                continue
            form = page.locator(f'[data-task="mapping"][data-id="{link["link_id"]}"]')
            reject = filenames[link["source_document_id"]] == "wrong.txt"
            if not reject:
                form.locator('[name="source"]').select_option(link["source_document_id"])
                form.locator('[name="identity"]').check()
            save_form(page, form, "Reject mapping" if reject else "Confirm identity")
        checkboxes = page.locator('[name="selected-link"]')
        assert checkboxes.count() == 3
        for i in range(checkboxes.count()):
            checkboxes.nth(i).check()
        page.get_by_role("button", name="Plan selected source links", exact=True).click()
        wait_idle(page)
        assert payloads == []  # extraction, parsing, identity and plan are zero-call gates
        page.get_by_role("button", name="Execute / retry safe items", exact=True).click()
        wait_idle(page)
        assert len(payloads) == 3
        page.reload()
        playwright.expect(page.locator("#matrix-view")).to_contain_text("review_pending")
        row = next(
            r
            for r in client.get(base + "/matrix").json()["rows"]
            if r["confirmed_claim"] == EDITED_CLAIM and r["audit_id"]
        )
        page.locator(f'tr[data-row="{row["row_id"]}"]').get_by_role(
            "link", name="Open ordinary audit v1"
        ).click()
        playwright.expect(page.locator("#reviewer")).to_be_visible()
        # Evidence correction and ordinary revision, followed by final human decision.
        page.locator("#reviewer").fill("Synthetic test reviewer")
        page.locator("#review-notes").fill(
            "Use an alternative original source passage, preserving traceability."
        )
        boxes = page.locator("[data-evidence-id]")
        assert boxes.count() >= 2
        page.get_by_text("Candidate evidence · select 1–3 passages", exact=True).click()
        for i in range(boxes.count()):
            boxes.nth(i).uncheck()
        boxes.nth(boxes.count() - 1).check()
        page.locator('[data-action="change-evidence"]').click()
        playwright.expect(page.locator("#review-status")).to_contain_text("New proposal ready")
        page.locator("#reviewer").fill("Synthetic test reviewer")
        page.locator("#review-notes").fill(
            "Final engineering acceptance after inspecting fictional evidence and proposal v2."
        )
        with page.expect_response(
            lambda r: r.request.method == "POST" and r.url.endswith("/reviews")
        ) as reviewed:
            page.locator('[data-action="accept"]').click()
        assert reviewed.value.status == 200
        playwright.expect(page.locator(".review-panel")).to_contain_text("Last action: accept")
        playwright.expect(page.locator('[data-action="accept"]')).to_be_disabled()
        assert len(payloads) == 4
        page.goto(url + "/projects?project=" + base.split("/")[-1])
        playwright.expect(page.locator("#matrix-view")).to_contain_text("accepted")
        row = next(
            r
            for r in client.get(base + "/matrix").json()["rows"]
            if r["audit_id"] == row["audit_id"]
        )
        trace = trace_for(client, base, row)
        assert verify_trace(**trace)["traceability_gate"] == "passed"
        # A deliberately broken join must prevent acceptance.
        trace["source"]["document_hash"] = "0" * 64
        with pytest.raises(AssertionError):
            verify_trace(**trace)
        # Production auth manager clears private content on sign-out, restores only
        # after explicit sign-in. SDK/server identity verification are mocked here.
        with pytest.raises(Exception, match="Save your guest workspace"):
            page.evaluate("window.ClaimTrellisAuth.signOut()")
        page.evaluate("window.ClaimTrellisAuth.switchToExistingAccount()")
        playwright.expect(page.locator("#paper-content")).to_be_empty()
        # Restore the same mocked session, not a new real anonymous identity.
        page.evaluate("localStorage.setItem('e2e-token', 'token-a')")
        page.reload()
        playwright.expect(page.locator("#matrix-view")).to_contain_text("accepted")
        other = browser.new_context()
        other.add_init_script(sdk_stub(users, "token-b"))
        other.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
        second = other.new_page()
        second.goto(url + "/projects?project=" + base.split("/")[-1])
        playwright.expect(second.locator("#paper-status")).to_contain_text("not found")
        for path in (
            base,
            base + "/sources/" + row["source_document_id"],
            "/api/v1/audits/" + row["audit_id"],
            base + "/matrix",
            base + "/audit-runs/" + row["run_id"],
        ):
            assert client.get(path, headers={"Authorization": "Bearer token-b"}).status_code == 404
        assert errors == []
        browser.close()


@pytest.mark.parametrize("width", [1440, 390, 320])
@pytest.mark.parametrize("theme", ["light", "night"])
def test_brand_lockup_all_pages_and_favicon(server, width, theme, tmp_path):
    url, users, payloads = server
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": width, "height": 1000})
        context.add_init_script(
            sdk_stub(users) + f"localStorage.setItem('claimtrellis-theme-v2','{theme}');"
        )
        context.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
        page = context.new_page()
        for path in ("/", "/history", "/projects"):
            page.goto(url + path)
            logo = page.locator("header .brand-lockup")
            playwright.expect(logo).to_be_visible()
            assert logo.evaluate("img => img.complete && img.naturalWidth === 923")
            assert logo.evaluate("img => img.naturalHeight") == 244
            rect = logo.bounding_box()
            assert abs(rect["width"] / rect["height"] - 923 / 244) < 0.01
            assert rect["x"] >= 0 and rect["x"] + rect["width"] <= width
            assert page.locator("header .alpha").count() == 0
            assert page.locator('link[rel="icon"]').get_attribute("href") == (
                "/assets/brand/favicon-32.png"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("html").get_attribute("data-theme") == theme
            page.screenshot(
                path=str(tmp_path / f"brand-{path.strip('/') or 'home'}-{width}-{theme}.png")
            )
        assert payloads == []
        browser.close()


@pytest.mark.parametrize(
    "width,theme", [(1440, "light"), (1440, "night"), (390, "light"), (390, "night")]
)
def test_entry_ui_sizes_arrows_and_keyboard(server, width, theme, tmp_path):
    url, users, payloads = server
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": 1000}, reduced_motion="reduce"
        )
        context.add_init_script(
            "localStorage.setItem('e2e-initialized','1');localStorage.removeItem('e2e-token');"
            + f"localStorage.setItem('claimtrellis-theme-v2','{theme}');"
            + sdk_stub(users)
        )
        context.route("https://cdn.jsdelivr.net/**", lambda route: route.abort())
        page = context.new_page()
        page.goto(url)
        primary, secondary = page.locator("#hero-primary"), page.locator("#hero-secondary")
        playwright.expect(secondary).to_be_visible()
        assert "📮" in secondary.inner_text() and "Sign in" in secondary.inner_text()
        for button in (primary, secondary, page.locator("#header-action")):
            assert "↗" not in button.inner_text()
        a, b = primary.bounding_box(), secondary.bounding_box()
        assert abs(a["width"] - b["width"]) < 0.5
        assert abs(a["height"] - b["height"]) < 0.5
        assert a["height"] >= 44 and a["width"] == 240
        assert page.locator(".hero-top,.hero-overline").count() == 0
        assert (
            page.locator(".home-header").evaluate(
                "header => getComputedStyle(header).borderBottomWidth"
            )
            == "0px"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("html").get_attribute("data-theme") == theme
        secondary.focus()
        page.keyboard.press("Enter")
        playwright.expect(page.locator("#account-dialog")).to_be_visible()
        page.locator("#account-close").click()
        playwright.expect(secondary).to_be_focused()
        assert payloads == []
        page.screenshot(path=str(tmp_path / f"entry-{width}-{theme}.png"))
        browser.close()
