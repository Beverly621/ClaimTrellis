(function (root) {
  const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
  function selectedIds(audit) {
    return (audit.evidence_set?.passages || (audit.selected_passage ? [audit.selected_passage] : []))
      .map((passage) => passage.passage_id);
  }
  function sameSelection(left, right) {
    return left.length === right.length && [...left].sort().every((id, i) => id === [...right].sort()[i]);
  }
  function validateSelection(ids, candidates) {
    if (!ids.length || ids.length > 3 || new Set(ids).size !== ids.length)
      throw new Error("Select one to three distinct evidence passages.");
    const allowed = new Set(candidates.map((item) => item.passage.passage_id));
    if (ids.some((id) => !allowed.has(id))) throw new Error("Select from this audit's source candidates.");
    return ids;
  }
  function renderCandidates(audit, selected, disabled) {
    return `<details class="supporting-context evidence-candidates"><summary>Candidate evidence · select 1–3 passages</summary>
      <p class="small muted">Selections take effect only after a new proposal is recorded. Lexical scores are ranking signals.</p>
      ${(audit.candidates || []).map((item) => `<div class="context-block"><label class="candidate-choice">
        <input type="checkbox" data-evidence-id="${escape(item.passage.passage_id)}" ${selected.includes(item.passage.passage_id) ? "checked" : ""} ${disabled ? "disabled" : ""}>
        #${item.rank} · ${escape(item.passage.locator)} · ${Number(item.score).toFixed(2)}</label>
        <p>${escape(item.passage.text)}</p></div>`).join("")}</details>`;
  }
  function dimensions(judgment, checks) {
    const rows = [["Provider relation", judgment?.relation?.choice || "Provider not run"]];
    for (const [key, name] of [["claim_type", "Claim type"], ["scope_alignment", "Scope / qualifiers"],
      ["population_alignment", "Population"], ["intervention_or_exposure_alignment", "Intervention / exposure"],
      ["comparator_alignment", "Comparator"], ["outcome_alignment", "Outcome"],
      ["timeframe_alignment", "Timeframe"], ["direction_alignment", "Direction"], ["causal_fidelity", "Causal fidelity"]]) {
      const value = judgment?.[key];
      rows.push([name, value ? `${value.choice.replaceAll("_", " ")} · confidence ${(value.confidence * 100).toFixed(1)}%` : "Not evaluated"]);
    }
    for (const finding of checks.findings || []) rows.push([finding.check_id, `${finding.status}: ${finding.reason}`]);
    return rows;
  }
  function renderVersion(version) {
    if (!version.evidence_set) return '<p class="muted">Legacy snapshot: evidence set not recorded.</p>';
    return `<p class="locator">Evidence set: ${escape(version.evidence_set.sha256)}</p>` +
      version.evidence_set.passages.map((passage) => `<div class="context-block"><p class="locator">${escape(passage.locator)}</p><p>${escape(passage.text)}</p></div>`).join("");
  }
  function renderChanges(previous, current) {
    const rows = [["Relation", previous.relation || "Not evaluated", current.relation || "Not evaluated"],
      ["Policy", previous.policy.status, current.policy.status]];
    if (previous.evidence_set?.sha256 !== current.evidence_set?.sha256) {
      const summary = (version) => version.evidence_set
        ? `${version.evidence_set.passages.length} passage(s) · ${version.evidence_set.sha256.slice(0, 12)}`
        : "Legacy evidence snapshot not recorded";
      rows.push(["Evidence set changed", summary(previous), summary(current)]);
    }
    for (const [key, name] of [["population_alignment", "Population"], ["intervention_or_exposure_alignment", "Intervention"],
      ["comparator_alignment", "Comparator"], ["outcome_alignment", "Outcome"], ["timeframe_alignment", "Timeframe"],
      ["direction_alignment", "Direction"], ["causal_fidelity", "Causal fidelity"], ["scope_alignment", "Scope"]]) {
      const oldValue = previous.judgment?.[key]?.choice || "Not evaluated";
      const newValue = current.judgment?.[key]?.choice || "Not evaluated";
      if (oldValue !== newValue) rows.push([name, oldValue, newValue]);
    }
    return rows.map(([name, oldValue, newValue]) => `<p class="change-line">${escape(name)}: <strong>${escape(oldValue)}</strong> → <strong>${escape(newValue)}</strong>${oldValue === newValue ? " (unchanged)" : ""}</p>`).join("");
  }
  const api = { selectedIds, sameSelection, validateSelection, renderCandidates, dimensions, renderVersion, renderChanges };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AuditFidelity = api;
})(typeof window !== "undefined" ? window : globalThis);
