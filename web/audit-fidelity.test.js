const test = require("node:test");
const assert = require("node:assert/strict");
const fidelity = require("./audit-fidelity.js");
const evidence = require("./evidence.js");

test("legacy and multi-passage selection resolve without mutating audit data", () => {
  const audit = { selected_passage: { passage_id: "p1" }, candidates: [{ passage: { passage_id: "p1" } }] };
  assert.deepEqual(fidelity.selectedIds(audit), ["p1"]);
  audit.evidence_set = { passages: [{ passage_id: "p2" }, { passage_id: "p1" }] };
  const before = JSON.stringify(audit);
  assert.deepEqual(fidelity.selectedIds(audit), ["p2", "p1"]);
  assert(fidelity.sameSelection(["p1", "p2"], ["p2", "p1"]));
  assert.equal(JSON.stringify(audit), before);
});
test("evidence selection requires 1–3 distinct IDs from the current source", () => {
  const candidates = ["p1", "p2", "p3", "p4"].map((id) => ({ passage: { passage_id: id } }));
  assert.deepEqual(fidelity.validateSelection(["p1", "p2"], candidates), ["p1", "p2"]);
  for (const ids of [[], ["p1", "p1"], ["foreign"], ["p1", "p2", "p3", "p4"]]) {
    assert.throws(() => fidelity.validateSelection(ids, candidates));
  }
});
test("candidate source content is escaped and finalized controls are disabled", () => {
  const audit = { candidates: [{ rank: 1, score: 2, passage: { passage_id: "p1", locator: "page:2", text: "<script>bad()</script>" } }] };
  const html = fidelity.renderCandidates(audit, ["p1"], true);
  assert(html.includes("checked disabled"));
  assert(html.includes("page:2"));
  assert(html.includes("&lt;script&gt;"));
  assert(!html.includes("<script>"));
});
test("outcome mismatch remains visible beside a raw supports judgment", () => {
  const rows = fidelity.dimensions({ relation: { choice: "supports" }, outcome_alignment: { choice: "mismatch", confidence: 0.95 } }, { findings: [] });
  assert(rows.some(([name, value]) => name === "Outcome" && value.includes("mismatch")));
  assert(rows.some(([name, value]) => name === "Timeframe" && value === "Not evaluated"));
});
test("multi-passage reading uses unique accessible heading IDs and actual locators", () => {
  const passage = { text: "Source sentence.", start_char: 0, end_char: 16, locator: "section:Results / paragraph:2", section: "Results", paragraph: 2 };
  const first = evidence.render("Claim.", passage, {}, "0");
  const second = evidence.render("Claim.", passage, {}, "1");
  assert(first.includes('id="primary-passage-title-0"'));
  assert(second.includes('id="primary-passage-title-1"'));
  assert(first.includes("section:Results / paragraph:2"));
});
test("evidence corrections remain visible even when provider relation is unchanged", () => {
  const previous = { relation: null, policy: { status: "review_required" }, evidence_set: { passages: [1, 2, 3], sha256: "old-hash" } };
  const current = { relation: null, policy: { status: "review_required" }, evidence_set: { passages: [1], sha256: "new-hash" } };
  const html = fidelity.renderChanges(previous, current);
  assert(html.includes("Evidence set changed"));
  assert(html.includes("3 passage(s)"));
  assert(html.includes("1 passage(s)"));
  assert(html.includes("(unchanged)"));
  assert(!html.includes("none"));
});
