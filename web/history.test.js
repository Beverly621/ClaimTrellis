const assert = require("node:assert/strict");
const { test } = require("node:test");
const { renderItem, mount } = require("./history.js");

const audit = {
  audit_id: "a&b",
  claim: "A <unsafe> claim",
  citation: "doi:example",
  source: { title: "study.pdf" },
  judgment_result: { relation: { choice: "supports" } },
  current_proposal_version: 2,
  review_status: "pending_review",
  provenance: { created_at: "2026-09-29T12:00:00Z" },
};

test("history record links to exact audit without exposing another user identifier", () => {
  const html = renderItem(audit);
  assert.match(html, /href="\/\?audit=a%26b#result"/);
  assert.match(html, /A &lt;unsafe&gt; claim/);
  assert.match(html, /study\.pdf/);
  assert.match(html, /supports · v2/);
  assert.doesNotMatch(html, /owner_user_id/);
});

test("history loading waits for guest auth and requests only the owned list endpoint", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const calls = [];
  const list = {
    innerHTML: "",
    insertAdjacentHTML(_where, html) { this.innerHTML += html; },
  };
  const status = { textContent: "" };
  const more = { hidden: true, disabled: false, addEventListener() {} };
  const nodes = { "#history-list": list, "#history-status": status, "#history-more": more };
  const auth = {
    start: () => gate,
    currentState: () => ({ kind: "guest" }),
    request: async (path) => { calls.push(path); return [audit]; },
  };
  const pending = mount({ querySelector: (selector) => nodes[selector] }, auth);
  await Promise.resolve();
  assert.deepEqual(calls, []);
  release();
  await pending;
  assert.deepEqual(calls, ["/api/v1/audits?limit=100&offset=0"]);
  assert.match(list.innerHTML, /audit=a%26b/);
  assert.equal(more.hidden, true);
});

test("signed-out history does not create a guest or fetch protected audits", async () => {
  const list = { innerHTML: "" };
  const status = { textContent: "" };
  const more = { hidden: false };
  await mount({ querySelector: (selector) => ({
    "#history-list": list, "#history-status": status, "#history-more": more,
  })[selector] }, {
    start: async () => {},
    currentState: () => ({ kind: "signed_out" }),
    request: () => assert.fail("protected history must not be fetched"),
  });
  assert.match(status.textContent, /Choose Continue as guest/);
  assert.match(list.innerHTML, /Open ClaimTrellis/);
  assert.equal(more.hidden, true);
});

test("cross-tab sign-out clears history and discards a late page response", async () => {
  let listener;
  let complete;
  let began;
  const ready = new Promise((resolve) => { began = resolve; });
  const list = { innerHTML: "", insertAdjacentHTML(_position, html) { this.innerHTML += html; } };
  const status = {};
  const more = { addEventListener() {} };
  const pending = mount({ querySelector: (selector) => ({
    "#history-list": list, "#history-status": status, "#history-more": more,
  })[selector] }, {
    start: async () => {}, currentState: () => ({ kind: "guest", userId: "original" }),
    onAuthStateChange: (callback) => { listener = callback; },
    request: () => { began(); return new Promise((resolve) => { complete = resolve; }); },
  });
  await ready;
  listener({ kind: "signed_out", userId: null });
  complete([audit]);
  await pending;
  assert.doesNotMatch(list.innerHTML, /unsafe|study.pdf/);
  assert.match(status.textContent, /session changed/);
  assert.equal(more.hidden, true);
});
