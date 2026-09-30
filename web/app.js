const $ = (selector) => document.querySelector(selector);
const esc = (value = "") =>
  String(value ?? "").replace(
    /[&<>'"]/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[
        c
      ],
  );
const label = (value) => String(value || "").replaceAll("_", " ");
const relations = [
  "supports",
  "partially_supports",
  "contradicts",
  "not_addressed",
  "insufficient_context",
  "source_unavailable",
];
const state = {
  audit: null,
  history: [],
  revisions: [],
  pendingRequest: null,
  busy: false,
  authReady: false,
  loadId: 0,
};
const percent = (value) =>
  Number.isFinite(value) ? (value * 100).toFixed(1) + "%" : "—";
const time = (value) =>
  new Date(value).toLocaleString([], {
    dateStyle: "short",
    timeStyle: "short",
  });
const reference = (audit) => ({
  proposal_id: audit.current_proposal_id,
  proposal_version: audit.current_proposal_version,
  expected_state_revision: audit.state_revision,
});
const activeRevision = (audit) =>
  ["revision_requested", "revision_running"].includes(audit.review_status);
const helpContent = {
  "review-guide": {
    title: "Review standard",
    body: `<ol class="guide-steps"><li><strong>Confirm identity.</strong><span>Is this the source the author intended?</span></li><li><strong>Inspect context.</strong><span>Read before and after the selected passage.</span></li><li><strong>Check boundaries.</strong><span>Population, endpoint, time, and causal strength matter.</span></li><li><strong>Own the result.</strong><span>Record a decision and explain it.</span></li></ol>`,
  },
  evidence: {
    title: "Selected evidence",
    body: `<dl class="action-guide"><dt>Primary passage</dt><dd>The source text most directly relevant to the claim.</dd><dt>Supporting context</dt><dd>Nearby source material preserved so the reviewer can inspect scope and qualification.</dd><dt>Source locator</dt><dd>Provenance information showing where the selected evidence came from.</dd></dl><p>The primary passage is a reading aid. The full selected evidence remains the canonical provider and audit input.</p>`,
  },
  relations: {
    title: "Relation probabilities",
    body: `<p>The provider assigns probability across six claim–source relations. The highlighted relation is the current proposal, not a guarantee of correctness.</p><p><strong>Partially supports</strong> means the source supports a material part of the claim, but not its full scope, population, endpoint, strength or causal interpretation.</p>`,
  },
  checks: {
    title: "Deterministic checks",
    body: `<p>Quote matching, number comparison and hashes are computed in code. Scope, population and causal fidelity are semantic provider judgments.</p><p>A warning identifies a boundary that needs attention; it does not silently decide the final outcome.</p>`,
  },
  timeline: {
    title: "Audit lifecycle",
    body: `<p>Summary mode foregrounds provider proposals, human feedback and final actions. Full audit mode preserves every append-only technical event.</p><p>Older proposals remain readable and cannot be silently overwritten.</p>`,
  },
  actions: {
    title: "Human actions",
    body: `<dl class="action-guide"><dt>Accept</dt><dd>Confirm the current proposal.</dd><dt>Revise with feedback</dt><dd>Return guidance to the provider and create a new proposal version.</dd><dt>Reject</dt><dd>Refuse the proposal without silently rerunning the provider.</dd><dt>Defer</dt><dd>Keep the audit pending for later review.</dd></dl><p>The current API records a note for every action. Revision feedback is review context, never replacement evidence.</p>`,
  },
};
let helpReturnFocus = null;

function openHelp(key, trigger) {
  const content = helpContent[key];
  const dialog = $("#help-dialog");
  if (!content || !dialog) return;
  helpReturnFocus = trigger;
  $("#help-title").textContent = content.title;
  $("#help-body").innerHTML = content.body;
  dialog.showModal();
  $(".help-close").focus();
}

const api = (path, options = {}) => ClaimTrellisAuth.request(path, options);
const post = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

async function loadHealth() {
  try {
    const health = await api("/healthz");
    $("#health").textContent = health.provider_configured
      ? "● Service online · provider ready"
      : "○ Service online · provider not configured";
    $("#provider-label").textContent =
      health.judgment_provider + " · " + health.jev_model;
  } catch {
    $("#health").textContent = "Service unavailable";
    $("#provider-label").textContent = "Provider status unavailable";
  }
}
function probabilityBars(judgment) {
  const top = judgment?.relation.choice;
  return relations
    .map((key) => {
      const value = judgment?.relation.probabilities[key];
      return `<div class="prob-row ${key === top ? "is-top" : ""}"><span>${key}</span><div class="prob-track"><div class="prob-fill" style="--prob:${Number.isFinite(value) ? Math.max(0, Math.min(100, value * 100)) : 0}%"></div></div><span>${percent(value)}</span></div>`;
    })
    .join("");
}
function metadata(rows) {
  return (
    '<dl class="metadata">' +
    rows
      .map(
        ([key, value]) =>
          `<div><dt>${esc(key)}</dt><dd>${esc(value ?? "Not available")}</dd></div>`,
      )
      .join("") +
    "</dl>"
  );
}
function renderAudit(audit, versions, revisions, events, draft = null) {
  state.audit = audit;
  state.revisions = revisions;
  const judgment = audit.judgment_result;
  const checks = audit.deterministic_checks;
  const passage = audit.selected_passage;
  const previous = versions.length > 1 ? versions[versions.length - 2] : null;
  const lastRun = revisions.at(-1);
  const feedback =
    draft?.feedback ??
    (lastRun?.status === "revision_failed" ? lastRun.request.feedback : "");
  const reviewer =
    draft?.reviewer ??
    audit.human_review?.reviewer ??
    lastRun?.request.reviewer ??
    "";
  const current = versions.at(-1);
  const processing = activeRevision(audit);
  const final = audit.review_status === "accepted";
  const warnings = [...checks.warnings, ...audit.service_errors];
  const checkRows = [
    ["Citation identity", "Human verification required"],
    [
      "Requested quote",
      !checks.quote_requested
        ? "Not requested"
        : checks.quote_found
          ? "Found in supplied source"
          : "Not found",
    ],
    [
      "Claim numbers",
      checks.claim_numbers.map((n) => n.raw).join(", ") || "None",
    ],
    [
      "Number comparison",
      checks.unmatched_claim_numbers.length
        ? "Unmatched: " +
          checks.unmatched_claim_numbers.map((n) => n.raw).join(", ")
        : checks.claim_numbers.length
          ? "Values present in passage"
          : "Not applicable",
    ],
    [
      "Scope / endpoint",
      judgment ? label(judgment.scope_alignment.choice) : "Provider not run",
    ],
    [
      "Population",
      judgment
        ? label(judgment.population_alignment.choice)
        : "Provider not run",
    ],
    [
      "Causal fidelity",
      judgment ? label(judgment.causal_fidelity.choice) : "Provider not run",
    ],
  ];
  $("#result").hidden = false;
  $("#result").innerHTML = `
    <div class="result-banner"><div><span class="micro">${final ? "HUMAN-CONFIRMED PROPOSAL" : "MODEL PROPOSAL"} / V${audit.current_proposal_version}</span><h3>${esc(judgment?.relation.choice || "No semantic judgment")}</h3></div><div class="proposal-score"><span>Probability</span><strong>${judgment ? percent(judgment.relation.probabilities[judgment.relation.choice]) : "—"}</strong></div><span class="status-badge status-${esc(audit.review_status)}">${esc(label(audit.review_status))}</span></div>
    <div class="result-grid"><div class="evidence-column">
      <section class="detail-panel evidence-panel"><div class="panel-heading"><h4>Claim & evidence</h4><button class="info-button" type="button" data-help="evidence" aria-label="About evidence selection">?</button></div><span class="field-label">CLAIM</span><blockquote class="claim-card">${esc(audit.claim)}</blockquote><div class="source-line"><span class="field-label">SOURCE</span><span>${esc(audit.source.title || audit.citation || "Uploaded source")} · ${esc(label(audit.source.access_tier))}</span></div><h4 class="selected-evidence-title">SELECTED EVIDENCE</h4>${EvidenceView.render(audit.claim, passage, audit.source)}</section>
      ${previous ? `<section class="detail-panel comparison-panel"><span class="field-label">WHAT CHANGED?</span><div class="revision-compare"><div><small>PROPOSAL V${previous.version}</small><p>${esc(previous.relation || "No judgment")}</p><small>${percent(previous.probabilities[previous.relation])}</small></div><span>→</span><div><small>PROPOSAL V${current.version}</small><p class="accent">${esc(current.relation || "No judgment")}</p><small>${percent(current.probabilities[current.relation])}</small></div></div><span class="field-label">HUMAN FEEDBACK</span><blockquote class="guidance">${esc(revisions.find((r) => r.result_proposal_id === current.proposal_id)?.request.feedback || "")}</blockquote><p class="change-line">Changed: <strong>${esc(previous.relation || "none")}</strong> → <strong>${esc(current.relation || "none")}</strong></p></section>` : ""}
      <section class="detail-panel probability-panel"><div class="panel-heading"><h4>Relation probabilities</h4><button class="info-button" type="button" data-help="relations" aria-label="About relation probabilities">?</button></div>${probabilityBars(judgment)}</section>
      <details class="detail-panel disclosure"><summary><span>Deterministic checks</span><span>${warnings.length ? `${warnings.length} attention` : "View checks"}</span></summary><div class="disclosure-body"><ul class="check-list">${checkRows.map(([a, b]) => `<li><span>${esc(a)}</span><span>${esc(b)}</span></li>`).join("")}</ul><button class="inline-help" type="button" data-help="checks">How these checks work ↗</button></div></details>
      <section class="detail-panel timeline-panel"><div class="panel-heading"><h4>Lifecycle</h4><button class="info-button" type="button" data-help="timeline" aria-label="About the audit timeline">?</button></div><div id="audit-timeline"></div><details class="technical-events"><summary>Show full audit events</summary><div id="full-audit-timeline"></div></details></section>
      <details class="detail-panel disclosure"><summary><span>Audit provenance</span><span>IDs, provider & policy</span></summary><div class="disclosure-body">${metadata(
        [
          ["Audit ID", audit.audit_id],
          ["Proposal ID", audit.current_proposal_id],
          ["Source hash", audit.source.content_sha256],
          ["Evidence hash", passage?.sha256],
          ["Claim hash", checks.normalized_claim_sha256],
          ["Provider", judgment?.provider],
          ["Model", judgment?.resolved_model],
          [
            "Question set",
            judgment?.question_set_version ??
              audit.provenance.question_set_version,
          ],
          ["Policy", audit.proposal.policy_version],
          ["Retrieval", audit.provenance.retrieval_version],
          ["Created", time(audit.provenance.created_at)],
          [
            "Provider latency",
            judgment ? Math.round(judgment.latency_ms) + " ms" : null,
          ],
          [
            "Tokens in / out",
            judgment
              ? judgment.input_tokens + " / " + judgment.output_tokens
              : null,
          ],
        ],
      )}</div></details>
      <details class="detail-panel disclosure"><summary><span>Proposal history</span><span>${versions.length} version${versions.length === 1 ? "" : "s"}</span></summary><div class="disclosure-body">${versions.map((version) => `<div class="instrument-row"><span>v${version.version} · ${esc(version.relation || "No judgment")}</span><span>${esc(label(version.review_status))}</span></div><p class="locator">${esc(version.proposal_id)} · ${esc(time(version.created_at))}</p>`).join("")}</div></details>
    </div><section class="detail-panel review-panel"><div class="panel-heading"><div><span class="field-label">HUMAN DECISION</span><h4>Human review / V${audit.current_proposal_version}</h4></div><button class="guide-trigger compact" type="button" data-help="review-guide">Review guide <span aria-hidden="true">?</span></button></div>
      ${judgment?.judgment_summary ? `<p class="judgment-summary">${esc(judgment.judgment_summary)}</p>` : ""}
      ${warnings.length ? `<div class="error small"><strong>Attention required</strong><ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
      ${audit.human_review ? `<p class="locator">Last action: ${esc(audit.human_review.decision)} · ${esc(audit.human_review.reviewer)} · ${esc(time(audit.human_review.created_at))}</p><blockquote class="guidance">${esc(audit.human_review.notes)}</blockquote>` : ""}
      <details class="review-rationale"><summary>Policy rationale</summary><ul class="reason-list">${audit.proposal.reasons.map((reason) => `<li>${esc(reason)}</li>`).join("")}</ul></details>
      <form id="review-form"><label for="reviewer">Reviewer alias</label><input id="reviewer" required maxlength="200" value="${esc(reviewer)}">
        <div class="feedback-label"><label for="review-notes">Human feedback</label><button class="info-button" type="button" data-help="actions" aria-label="About review action requirements">?</button></div><textarea id="review-notes" required maxlength="10000" rows="5" placeholder="Add a concise decision note, or guidance for a revision.">${esc(feedback)}</textarea>
        <p class="feedback-contract">Revise and Reject need substantive feedback. The current API also records a short note for Accept and Defer.</p>
        <div class="review-actions"><button class="button accept-action" type="submit" data-action="accept" ${final || processing || !judgment || audit.service_errors.length || audit.review_status === "rejected" ? "disabled" : ""}>Accept proposal <span>✓</span></button><button class="button revise-action" type="submit" data-action="revise" ${final || processing ? "disabled" : ""}>${audit.review_status === "revision_failed" ? "Retry revision" : "Revise with feedback"} <span>↻</span></button><button class="quiet-action reject-action" type="submit" data-action="reject" ${final || processing || audit.review_status === "rejected" ? "disabled" : ""}>Reject</button><button class="quiet-action defer-action" type="submit" data-action="defer" ${final || processing || audit.review_status === "rejected" ? "disabled" : ""}>Defer</button></div>
      </form>
      <p id="review-status" role="status" aria-live="polite">${processing ? "Re-evaluating evidence. Awaiting the provider response…" : final ? "This proposal version is accepted. The complete history is preserved." : audit.review_status === "rejected" ? "Proposal rejected. Use feedback to request a new judgment." : audit.review_status === "revision_failed" ? "Revision failed. Original proposal and feedback preserved." : "Awaiting your review."}</p>
      <button id="reload-audit" type="button" class="text-link" style="background:none;border:0;border-bottom:1px solid #485450;margin-top:18px;padding-inline:0">Refresh current record ↻</button>
    </section></div>`;
  renderTimeline(events, false);
  renderTimeline(events, true);
  $("#reviewer").disabled = state.busy;
  $("#review-notes").disabled = state.busy;
  $("#review-form").addEventListener("submit", handleReview);
  $("#reload-audit").addEventListener("click", () =>
    refreshCurrent(true).catch(showReviewError),
  );
}
const eventNames = {
  "audit.created": "Audit opened",
  "source.loaded": "Source loaded",
  "checks.completed": "Deterministic checks recorded",
  "proposal.created": "Provider proposal recorded",
  "feedback.recorded": "Human feedback recorded",
  "revision.requested": "Revision requested",
  "revision.started": "Re-evaluating evidence",
  "revision.failed": "Revision failed",
  "revision.completed": "New proposal ready",
  "proposal.superseded": "Previous proposal superseded",
  "review.accepted": "Human accepted",
  "review.rejected": "Human rejected",
  "review.deferred": "Decision deferred",
  "review.recorded": "Legacy review recorded",
};
function renderTimeline(events, full) {
  const container = $(full ? "#full-audit-timeline" : "#audit-timeline");
  if (!container) return;
  const lifecycleTypes = new Set([
    "proposal.created",
    "feedback.recorded",
    "revision.failed",
    "review.accepted",
    "review.rejected",
    "review.deferred",
  ]);
  const visibleEvents = full
    ? events
    : events.filter((event) => lifecycleTypes.has(event.event_type));
  container.innerHTML =
    `<ol class="timeline ${full ? "timeline-full" : "timeline-summary"}">` +
    visibleEvents
      .map((event) => {
        const data = event.payload;
        const description =
          !full && event.event_type === "proposal.created"
            ? "Proposal"
            : event.event_type === "proposal.created" &&
                !data.proposal?.judgment
              ? "Deterministic proposal recorded"
              : eventNames[event.event_type] || event.event_type;
        return `<li><div class="timeline-title"><span>${esc(description)}${event.proposal_version ? " · v" + event.proposal_version : ""}</span><time datetime="${esc(event.created_at)}">${esc(time(event.created_at))}</time></div>${data.feedback ? `<blockquote class="guidance">${esc(data.feedback)}</blockquote>` : ""}${data.message ? `<p class="error small">${esc(data.message)}</p>` : ""}${data.review ? `<p class="locator">${esc(data.review.reviewer)} · ${esc(data.review.notes)}</p>` : ""}${data.proposal?.relation ? `<p class="locator">${esc(data.proposal.relation)} · ${percent(data.proposal.probabilities[data.proposal.relation])}</p>` : ""}</li>`;
      })
      .join("") +
    "</ol>";
}
function draft() {
  return {
    feedback: $("#review-notes")?.value || "",
    reviewer: $("#reviewer")?.value || "",
  };
}
function showReviewError(error) {
  if ($("#review-status")) $("#review-status").textContent = error.message;
}

async function openAudit(id, preserve = false) {
  const loadId = ++state.loadId;
  const saved = preserve ? draft() : null;
  const base = "/api/v1/audits/" + encodeURIComponent(id);
  const [audit, versions, revisions, events] = await Promise.all([
    api(base),
    api(base + "/proposals"),
    api(base + "/revisions"),
    api(base + "/events"),
  ]);
  if (loadId !== state.loadId) return;
  renderAudit(audit, versions, revisions, events, saved);
  const url = new URL(window.location.href);
  url.searchParams.set("audit", audit.audit_id);
  url.hash = "result";
  window.history.replaceState(null, "", url);
}
function clearAuditUrl() {
  const url = new URL(window.location.href);
  url.searchParams.delete("audit");
  if (url.hash === "#result") url.hash = "workspace";
  window.history.replaceState(null, "", url);
}
async function refreshCurrent(preserve = false) {
  if (state.busy || !state.audit) return;
  await openAudit(state.audit.audit_id, preserve);
}
function setBusy(busy) {
  state.busy = busy;
  $("#submit-button").disabled = busy || !state.authReady;
  $("#refresh-history").disabled = busy || !state.authReady;
  document.querySelectorAll("[data-audit-id]").forEach((button) => {
    button.disabled = busy;
  });
  if ($("#reload-audit")) $("#reload-audit").disabled = busy;
  if ($("#reviewer")) $("#reviewer").disabled = busy;
  if ($("#review-notes")) $("#review-notes").disabled = busy;
  if (busy)
    document.querySelectorAll("[data-action]").forEach((button) => {
      button.disabled = true;
    });
}
async function handleReview(event) {
  event.preventDefault();
  if (state.busy || !state.audit) return;
  const action = event.submitter?.dataset.action;
  if (!action) return;
  const audit = state.audit;
  const input = draft();
  if (!input.feedback.trim() || !input.reviewer.trim()) {
    showReviewError(new Error("Enter a reviewer alias and reasoned feedback."));
    return;
  }
  const base = "/api/v1/audits/" + encodeURIComponent(audit.audit_id);
  setBusy(true);
  let polling = null;
  try {
    if (action === "revise") {
      // Retain the same request on a network-ambiguous retry.
      const existing = state.pendingRequest;
      const request =
        existing?.auditId === audit.audit_id
          ? existing.body
          : {
              ...reference(audit),
              feedback: input.feedback,
              reviewer: input.reviewer,
              idempotency_key: crypto.randomUUID(),
            };
      state.pendingRequest = { auditId: audit.audit_id, body: request };
      $("#review-status").textContent = "Submitting human guidance…";
      const poll = async () => {
        try {
          const events = await api(base + "/events");
          if (!polling || state.audit?.audit_id !== audit.audit_id) return;
          renderTimeline(events);
          const last = events.at(-1);
          if (last && $("#review-status"))
            $("#review-status").textContent =
              eventNames[last.event_type] || label(last.event_type);
        } catch {
          /* The POST response or a later refresh resolves transient poll failures. */
        }
      };
      polling = setInterval(poll, 1200);
      const run = await post(base + "/revisions", request);
      state.pendingRequest = null;
      clearInterval(polling);
      polling = null;
      await openAudit(audit.audit_id, run.status !== "revision_completed");
      $("#review-status").textContent =
        run.status === "revision_completed"
          ? "New proposal ready. Review the changed relation and record your decision."
          : run.status === "revision_failed"
            ? run.error_message
            : "Revision is already running. Refresh the record to see its outcome.";
    } else {
      await post(base + "/reviews", {
        ...reference(audit),
        decision: action,
        notes: input.feedback,
        reviewer: input.reviewer,
      });
      await openAudit(audit.audit_id);
    }
    await loadHistory();
  } catch (error) {
    if (error.status) state.pendingRequest = null;
    await openAudit(audit.audit_id, true).catch(() => {});
    showReviewError(
      new Error(
        error.status === 409
          ? error.message +
            " Your feedback is retained; inspect the current proposal."
          : error.message +
            (state.pendingRequest
              ? " Retry resends the same request safely."
              : ""),
      ),
    );
  } finally {
    if (polling) clearInterval(polling);
    polling = null;
    setBusy(false);
    // If a refresh also failed, restore controls based on the last known record.
    if (
      $("#review-form") &&
      $("#review-form").querySelectorAll("[data-action]:not(:disabled)")
        .length === 0 &&
      state.audit?.review_status === "pending_review"
    ) {
      await refreshCurrent(true).catch(showReviewError);
    }
  }
}

async function loadHistory() {
  const container = $("#history");
  try {
    const audits = await api("/api/v1/audits?limit=10");
    state.history = audits;
    container.innerHTML = audits.length
      ? audits
          .map(
            (audit) =>
              `<button class="history-item" type="button" data-audit-id="${esc(audit.audit_id)}"><time datetime="${esc(audit.provenance.created_at)}">${esc(time(audit.provenance.created_at))}</time><span class="history-claim">${esc(audit.claim.slice(0, 140))}<small>${esc(audit.source.title || audit.citation || "Uploaded source")}</small></span><span class="mono">${esc(audit.judgment_result?.relation.choice || "Not evaluated")} · v${audit.current_proposal_version}</span><span class="status-badge status-${esc(audit.review_status)}">${esc(label(audit.review_status))}</span></button>`,
          )
          .join("")
      : '<p class="empty">Your first claim starts the record. No audits yet.</p>';
    container.querySelectorAll("button").forEach((button) =>
      button.addEventListener("click", async () => {
        if (state.busy) return;
        button.disabled = true;
        try {
          await openAudit(button.dataset.auditId);
          $("#result").scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
              ? "instant"
              : "smooth",
          });
        } catch (error) {
          container.insertAdjacentHTML(
            "afterbegin",
            `<p role="alert" class="error">${esc(error.message)}</p>`,
          );
        } finally {
          button.disabled = false;
        }
      }),
    );
  } catch (error) {
    container.innerHTML = `<p class="error" role="alert">${esc(error.message)}</p>`;
  }
}
const sourceInput = $("#source-file");
function selectedFile() {
  const file = sourceInput.files?.[0];
  sourceInput.setCustomValidity("");
  if (
    file &&
    (!/\.(txt|md|pdf|docx)$/i.test(file.name) || file.size > 25 * 1024 * 1024)
  ) {
    sourceInput.setCustomValidity(
      "Choose a TXT, MD, PDF or DOCX file up to 25 MB.",
    );
  }
  $("#file-name").textContent = file
    ? file.name + " · " + (file.size / 1024).toFixed(1) + " KB"
    : "TXT, MD, PDF or DOCX · up to 25 MB";
}
sourceInput.addEventListener("change", selectedFile);
const drop = $("#file-drop");
["dragenter", "dragover"].forEach((type) =>
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.add("dragover");
  }),
);
["dragleave", "drop"].forEach((type) =>
  drop.addEventListener(type, (event) => {
    event.preventDefault();
    drop.classList.remove("dragover");
  }),
);
drop.addEventListener("drop", (event) => {
  if (state.busy || !event.dataTransfer.files.length) return;
  const files = new DataTransfer();
  files.items.add(event.dataTransfer.files[0]);
  sourceInput.files = files.files;
  selectedFile();
  sourceInput.reportValidity();
});
$("#audit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy || !state.authReady) return;
  const file = sourceInput.files?.[0];
  if (!file) return;
  // Snapshot all inputs before awaiting file parsing.
  const input = {
    claim: $("#claim").value,
    citation: $("#citation").value || null,
    quote: $("#quote").value || null,
    access: $("#access-tier").value,
    provider: $("#use-provider").checked,
  };
  setBusy(true);
  ++state.loadId;
  $("#form-status").textContent = "Parsing the source…";
  try {
    const data = new FormData();
    data.append("document", file);
    const parsed = await api("/api/v1/documents/parse", {
      method: "POST",
      body: data,
    });
    $("#form-status").textContent =
      "Source parsed. Retrieving, checking and evaluating evidence…";
    const audit = await post("/api/v1/audits", {
      claim: input.claim,
      citation: input.citation,
      quote: input.quote,
      source_text: parsed.text,
      source: {
        title: file.name,
        access_tier: input.access,
        content_sha256: parsed.content_sha256,
      },
      use_judgment_provider: input.provider,
      top_k: 5,
    });
    state.pendingRequest = null;
    await openAudit(audit.audit_id);
    await loadHistory();
    $("#form-status").textContent =
      "Audit recorded. Human review required." +
      (parsed.warnings.length ? " " + parsed.warnings.join(" ") : "");
    $("#result").scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  } catch (error) {
    $("#form-status").textContent = error.message;
  } finally {
    setBusy(false);
    if (state.audit) await refreshCurrent(true).catch(showReviewError);
  }
});
$("#refresh-history").addEventListener("click", () => {
  if (state.authReady) loadHistory();
});
document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-help]");
  if (trigger) openHelp(trigger.dataset.help, trigger);
});
$(".help-close").addEventListener("click", () => $("#help-dialog").close());
$("#help-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
$("#help-dialog").addEventListener("close", () => helpReturnFocus?.focus());
async function bootstrapWorkspace() {
  state.authReady = false;
  setBusy(false);
  $("#form-status").textContent = "Preparing your workspace…";
  try {
    await ClaimTrellisAuth.start();
    state.authReady = true;
    setBusy(false);
    $("#workspace-identity").hidden = false;
    $("#form-status").textContent = "Ready when you are.";
    await Promise.all([loadHealth(), loadHistory()]);
    const auditId = new URL(window.location.href).searchParams.get("audit");
    if (auditId) {
      try {
        await openAudit(auditId);
        $("#result").scrollIntoView({ behavior: "instant" });
      } catch (error) {
        if (error.status === 404) {
          clearAuditUrl();
          $("#form-status").textContent = "That audit is unavailable in this workspace.";
        } else {
          $("#form-status").textContent = error.message;
        }
      }
    }
  } catch (error) {
    $("#form-status").innerHTML = `${esc(error.message)} <button id="retry-workspace" type="button" class="text-link">Retry workspace ↻</button>`;
    $("#retry-workspace").addEventListener("click", bootstrapWorkspace);
  }
}
bootstrapWorkspace();
