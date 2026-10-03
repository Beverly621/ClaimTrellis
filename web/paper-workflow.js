(function (root) {
  const esc = (v = "") => String(v ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]);
  const id = v => encodeURIComponent(v);
  const key = () => root.crypto.randomUUID();
  const options = (records, field, label) => records.map(r => `<option value="${esc(r[field])}">${esc(label(r))}</option>`).join("");
  const human = `<label>Reviewer alias<input name="reviewer" required maxlength="200"></label><label>Decision notes<textarea name="notes" required maxlength="4000"></textarea></label>`;

  function renderCandidate(c) {
    const original = `<details><summary>Original sentence / exact span</summary><p>${esc(c.source_sentence)}</p><blockquote>${esc(c.original_span)}</blockquote><p class="mono">${esc(c.exact_span_start)}–${esc(c.exact_span_end)} · ${esc(c.sha256)}</p><p>${esc(c.extraction_warnings?.join(" · "))}</p></details>`;
    if (c.status !== "pending") return `<article class="paper-card"><h3>${esc(c.status)} claim</h3><p>${esc(c.confirmed_claim || c.original_span)}</p>${original}</article>`;
    return `<article class="paper-card"><h3>Claim awaiting human confirmation</h3>${original}<form data-task="claim" data-id="${esc(c.candidate_id)}" data-revision="${esc(c.state_revision)}"><label>Confirm or edit claim<textarea name="claim" required maxlength="20000">${esc(c.original_span)}</textarea></label><fieldset><legend>Human rubric (required for Confirm/Edit)</legend>${["atomic", "faithful", "necessary_context"].map(n => `<label><input type="checkbox" name="${n}">${esc(n.replaceAll("_"," "))}</label>`).join("")}</fieldset>${human}<button type="submit" name="decision" value="confirm" class="button secondary">Confirm / save edit</button><button type="submit" name="decision" value="reject" class="button secondary" formnovalidate>Reject candidate</button></form></article>`;
  }

  function renderMapping(row, sources) {
    const summary = `<p>${esc(row.confirmed_claim || row.original_span)}</p><blockquote>${esc(row.citation)}</blockquote>`;
    if (["claim_pending","claim_rejected"].includes(row.workflow_state)) return `<article class="paper-card"><h3>${esc(row.workflow_state)}</h3>${summary}<p>Confirm the claim before mapping a source.</p></article>`;
    if (row.mapping_status !== "pending") return "";
    return `<article class="paper-card"><h3>Source identity awaiting human confirmation</h3>${summary}<form data-task="mapping" data-id="${esc(row.row_id)}" data-revision="${esc(row.mapping_state_revision)}"><label>Uploaded source<select name="source"><option value="">Choose the actual source</option>${options(sources,"source_document_id",s => `${s.filename} · ${s.metadata.title || "Untitled"} · ${s.document_hash.slice(0,12)}`)}</select></label><label><input type="checkbox" name="identity">I checked this source's identity against the original reference.</label>${human}<button type="submit" name="decision" value="confirm" class="button secondary">Confirm identity</button><button type="submit" name="decision" value="reject" class="button secondary" formnovalidate>Reject mapping</button></form></article>`;
  }

  function renderRow(row, project) {
    const canRun = ["audit_pending", "quota_blocked"].includes(row.workflow_state) || (row.workflow_state === "audit_failed" && row.retry_allowed);
    const auditLink = row.audit_id ? `<a href="/?audit=${id(row.audit_id)}&project=${id(project)}#result">Open ordinary audit v${esc(row.proposal_version)}</a>` : "Not yet audited";
    const sourceCell = row.source_document_id ? `<span>${esc(row.source?.title || row.source?.filename || row.source_document_id)}</span><small class="paper-block">${esc(row.source?.document_hash || "")}</small><button type="button" data-source="${esc(row.source_document_id)}">Read uploaded source</button>` : "Unmapped";
    return `<tr data-row="${esc(row.row_id)}">
      <td>${canRun ? `<label><input type="checkbox" name="selected-link" value="${esc(row.row_id)}">Select</label>` : "—"}</td>
      <td>${esc(row.confirmed_claim || row.original_span)}<small class="paper-block">Claim ${esc(row.candidate_id)}</small></td>
      <td>${esc(row.citation)}<small class="paper-block">Reference ${esc(row.reference_id)}</small></td>
      <td>${sourceCell}</td>
      <td>${row.evidence.map(p => `<details><summary>${esc(p.locator)}</summary><blockquote>${esc(p.text)}</blockquote><small>${esc(p.sha256)}</small></details>`).join("") || "—"}</td>
      <td>${esc(row.raw_relation || "Not evaluated")}</td>
      <td>${esc(row.policy_status || "—")}<small class="paper-block">${esc(row.policy_reasons.join(" · "))}</small></td>
      <td>${esc(row.error_code || row.service_errors.join(" · ") || "—")}</td>
      <td>${esc(row.workflow_state)}<small class="paper-block">${esc(row.human_decision || "No human decision")}</small>${auditLink}</td>
    </tr>`;
  }

  function renderMatrix(matrix, project, filter = "", sort = "claim") {
    const rows = matrix.rows.filter(r => !filter || r.workflow_state === filter);
    rows.sort((a,b) => String(sort === "workflow" ? a.workflow_state : a.confirmed_claim || a.original_span).localeCompare(String(sort === "workflow" ? b.workflow_state : b.confirmed_claim || b.original_span)) || a.row_id.localeCompare(b.row_id));
    return `<p>${Object.entries(matrix.counts).map(([s,n]) => `${esc(s)}: ${esc(n)}`).join(" · ") || "No mappings yet"}</p><div class="paper-table-wrap"><table class="paper-matrix"><caption>Evidence Matrix — one row per claim-to-source link (${rows.length} shown / ${matrix.total} total). Counts are workflow counts, not paper quality scores.</caption><thead><tr>${["Run","Claim","Citation","Source","Selected evidence","Raw relation","Policy proposal","Issue flags","Human review / workflow"].map(h => `<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows.map(r => renderRow(r,project)).join("")}</tbody></table></div>`;
  }

  async function runQueue(items, execute, isCurrent, onResult, concurrency = 2) {
    let cursor = 0, stop = false;
    async function worker() {
      while (!stop && isCurrent() && cursor < items.length) {
        const item = items[cursor++];
        if (item.status === "completed" || item.status === "running" || item.retry_allowed === false) continue;
        const result = await execute(item);
        if (!isCurrent()) return;
        await onResult(result);
        if (result.status === "quota_blocked" || result.error_code === "provider_outcome_unknown") stop = true;
      }
    }
    await Promise.all(Array.from({length: Math.min(2, Math.max(1, concurrency))}, worker));
  }

  async function pages(auth, path, current) {
    let records = [], offset = 0;
    while (current()) {
      const batch = await auth.request(`${path}?limit=200&offset=${offset}`);
      if (!current()) return [];
      const rows = Array.isArray(batch) ? batch : batch.rows;
      records.push(...rows);
      offset += rows.length;
      if (rows.length < 200 || (!Array.isArray(batch) && offset >= batch.total)) return Array.isArray(batch) ? records : {...batch,rows:records,offset:0};
      if (offset >= 10000) throw new Error("This workspace exceeds the browser's 10,000-record view limit. Use the paginated API; no rows were silently omitted.");
    }
    return [];
  }

  async function mount(doc, auth) {
    const $ = s => doc.querySelector(s);
    const status = $("#paper-status"), content = $("#paper-content"), controls = $("#project-controls"), select = $("#project-select");
    let generation = 0, invalid = false, project = "", data = null, selected = new Set(), busy = false;
    const controller = new AbortController(), request = auth.request.bind(auth);
    auth = {...auth, request: (path,options={}) => {
      if(invalid) throw new Error("Workspace session changed.");
      return request(path,{...options,signal:controller.signal});
    }};
    const report = message => { if (!invalid) status.textContent = message; };
    function clear(next) {
      invalid = true; controller.abort(); generation++; project = ""; data = null; selected.clear();
      content.innerHTML = ""; controls.hidden = true; select.innerHTML = '<option value="">Choose a project</option>';
      $("#project-name").value = "";
      status.textContent = next || "Your account session changed. Reopen this page from your workspace.";
    }
    async function post(path, body) { return auth.request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); }
    async function refreshProjects() {
      const token = generation, current = () => !invalid && token === generation;
      const projects = await pages(auth,"/api/v1/projects",current);
      if (!current()) return;
      select.innerHTML = '<option value="">Choose a project</option>' + options(projects,"project_id",p=>p.name);
      select.value = project;
    }
    async function load() {
      if (invalid || !project) return;
      const token = ++generation, chosen = project, current = () => !invalid && token === generation && chosen === project;
      content.innerHTML = ""; selected.clear(); report("Loading persisted project state…");
      const base = `/api/v1/projects/${id(chosen)}`;
      const [manuscripts,sources,matrix,runs] = await Promise.all([pages(auth,`${base}/manuscripts`,current),pages(auth,`${base}/sources`,current),pages(auth,`${base}/matrix`,current),pages(auth,`${base}/audit-runs`,current)]);
      if (!current()) return;
      const bundles = await Promise.all(manuscripts.map(async m => ({m, candidates:await pages(auth,`${base}/manuscripts/${id(m.manuscript_id)}/candidates`,current),refs:await pages(auth,`${base}/manuscripts/${id(m.manuscript_id)}/references`,current)})));
      if (!current()) return;
      data = {base,manuscripts,sources,matrix,runs,bundles};
      draw(); report("Loaded. Human decisions are required; no audit has been silently started.");
    }
    function draw() {
      const {manuscripts,sources,matrix,runs,bundles} = data;
      content.innerHTML = `<section class="paper-section"><h2>1. Manuscripts &amp; claim review</h2><form data-task="manuscript"><label>Manuscript (TXT / MD / PDF / DOCX)<input name="file" type="file" accept=".txt,.md,.pdf,.docx" required></label><button class="button secondary" type="submit">Upload manuscript</button></form>${bundles.map(({m,candidates,refs}) => `<article class="paper-card"><h3>${esc(m.filename)}</h3><p class="mono">${esc(m.content_sha256)}</p><button type="button" data-extract="${esc(m.manuscript_id)}">Extract exact-span candidates</button><button type="button" data-references="${esc(m.manuscript_id)}">Parse references</button>${candidates.map(renderCandidate).join("")}<details><summary>Original reference entries (${refs.length})</summary>${refs.map(r=>`<blockquote>${esc(r.raw_reference)}</blockquote><small>${esc(r.sha256)}</small>`).join("")}</details></article>`).join("")}</section>
      <section class="paper-section"><h2>2. References, sources &amp; identity review</h2><form data-task="source"><label>Source file<input name="file" type="file" accept=".txt,.md,.pdf,.docx" required></label><label>Title<input name="title" maxlength="2000"></label><label>DOI (suggestion only)<input name="doi" maxlength="500"></label><label>Year<input name="year" type="number" min="1900" max="2100"></label><label>Access tier<select name="tier"><option value="unknown">Unknown</option><option value="full_text">Full text</option><option value="abstract">Abstract</option><option value="excerpt">Excerpt</option></select></label><button class="button secondary" type="submit">Upload source</button></form><details><summary>Manual reference / source association</summary><form data-task="reference"><label>Manuscript<select name="manuscript" required>${options(manuscripts,"manuscript_id",m=>m.filename)}</select></label><label>Reference exact-span start<input name="start" type="number" min="0" required></label><label>Reference exact-span end<input name="end" type="number" min="1" required></label><label>Citation marker<input name="marker" required placeholder="[12]"></label><button type="submit">Save grounded reference</button></form><form data-task="association"><label>Confirmed claim<select name="candidate" required>${options(bundles.flatMap(b=>b.candidates).filter(c=>c.status==="confirmed"),"candidate_id",c=>c.confirmed_claim)}</select></label><label>Original reference<select name="reference" required>${options(bundles.flatMap(b=>b.refs),"reference_id",r=>r.raw_reference)}</select></label><label>Uploaded source<select name="source"><option value="">Unmapped</option>${options(sources,"source_document_id",s=>s.filename)}</select></label><button type="submit">Create pending mapping</button></form></details><button id="suggest-all" type="button" class="button secondary">Suggest mappings for confirmed claims (not confirmation)</button>${matrix.rows.map(r=>renderMapping(r,sources)).join("")}<div id="source-inspector" aria-live="polite"></div></section>
      <section class="paper-section"><h2>3. Audit queue</h2><p>Select eligible rows below. Planning does not call Jev. Execute at most two item requests at once; blocked or unknown outcomes stop further scheduling.</p><label><input id="paper-provider" type="checkbox" checked>Use configured judgment provider (requires explicit paper budgets)</label><button id="plan-run" type="button" class="button secondary">Plan selected source links</button><div id="run-list">${runs.map(r=>`<article class="paper-card"><h3>Run ${esc(r.run_id)} · ${esc(r.status)}</h3><p>Preflight estimate: ${r.quota.requested_links} requested · ${r.quota.runnable_now} runnable now · ${r.quota.blocked} blocked. ${esc(r.quota.reason || "")} Actual calls require atomic reservation.</p><p>${r.items.map(i=>`${esc(i.status)} (${esc(i.error_code || "no error")})`).join(" · ")}</p><button type="button" data-run="${esc(r.run_id)}" ${busy ? "disabled" : ""}>Execute / retry safe items</button></article>`).join("")}</div></section>
      <section class="paper-section"><h2>4. Evidence Matrix</h2><label>Workflow filter<select id="matrix-filter"><option value="">All workflow states</option>${options(Object.keys(matrix.counts).map(s=>({s})),"s",r=>r.s)}</select></label><label>Sort<select id="matrix-sort"><option value="claim">Claim</option><option value="workflow">Workflow state</option></select></label><a id="next-review" href="${nextReview(matrix.rows,project) || "#paper-main"}">Open next pending ordinary audit</a><div id="matrix-view">${renderMatrix(matrix,project)}</div></section><section class="paper-section"><h2>Workflow provenance</h2><button id="show-events" type="button">Read project event history</button><div id="paper-events"></div></section>`;
      $("#matrix-filter").addEventListener("change", redrawMatrix);
      $("#matrix-sort").addEventListener("change", redrawMatrix);
      $("#plan-run").addEventListener("click", () => action(async () => { const ids=[...selected]; if (!ids.length) throw new Error("Select at least one eligible matrix row."); if (ids.length>200) throw new Error("A run may contain at most 200 source links."); await post(`${data.base}/audit-runs`,{idempotency_key:key(),source_link_ids:ids,use_judgment_provider:$("#paper-provider").checked}); await load(); }));
      $("#suggest-all").addEventListener("click", () => action(async () => { for (const c of bundles.flatMap(b=>b.candidates).filter(c=>c.status==="confirmed")) {if(invalid)return; await post(`${data.base}/candidates/${id(c.candidate_id)}/suggest-mappings`,{});} await load(); }));
      $("#show-events").addEventListener("click", () => action(async () => {const token=generation; const events=await pages(auth,`${data.base}/events`,()=>!invalid && generation===token); if(!invalid && generation===token) $("#paper-events").innerHTML=events.map(e=>`<details><summary>${esc(e.event_type)} · ${esc(e.record_id)}</summary><pre>${esc(JSON.stringify(e.payload,null,2))}</pre></details>`).join("");}));
    }
    function redrawMatrix() {
      $("#matrix-view").innerHTML=renderMatrix(data.matrix,project,$("#matrix-filter").value,$("#matrix-sort").value);
      doc.querySelectorAll('input[name="selected-link"]').forEach(el=>{el.checked=selected.has(el.value);});
    }
    async function action(fn) {
      if(invalid || busy)return;
      busy=true; controls.querySelectorAll?.("button,input,select").forEach(el=>el.disabled=true);
      content.setAttribute("aria-busy","true");
      try {await fn();} catch(error) {if(!invalid) {if(error.status===409) {await load(); report(`Stale decision: ${error.message} State refreshed; nothing was automatically resubmitted.`);} else report(error.message);}}
      finally {busy=false; if(!invalid){content.setAttribute("aria-busy","false"); controls.querySelectorAll?.("button,input,select").forEach(el=>el.disabled=false);content.querySelectorAll("[data-run]").forEach(el=>el.disabled=false);}}
    }
    content.addEventListener("change", e=>{if(e.target.name==="selected-link") e.target.checked ? selected.add(e.target.value) : selected.delete(e.target.value);});
    content.addEventListener("submit", e=>{e.preventDefault(); const form=e.target,task=form.dataset.task,button=e.submitter,values=new FormData(form); action(async()=>{
      const base=data.base, token=generation, current=()=>!invalid && generation===token;
      const decision=button?.value || "confirm";
      if(task==="claim") {const c=data.bundles.flatMap(b=>b.candidates).find(c=>c.candidate_id===form.dataset.id); const claim=String(values.get("claim")).trim(); const edited=claim!==c.original_span; await post(`${base}/candidates/${id(c.candidate_id)}/decisions`,{idempotency_key:key(),expected_state_revision:c.state_revision,reviewer:values.get("reviewer"),notes:values.get("notes"),decision:decision==="reject" ? "reject" : edited ? "edit" : "confirm",...(decision!=="reject" ? {rubric:Object.fromEntries(["atomic","faithful","necessary_context"].map(n=>[n,values.has(n)])),...(edited ? {confirmed_claim:claim} : {})} : {})});}
      else if(task==="mapping") await post(`${base}/source-links/${id(form.dataset.id)}/decisions`,{idempotency_key:key(),expected_state_revision:Number(form.dataset.revision),decision,reviewer:values.get("reviewer"),notes:values.get("notes"),identity_confirmed:decision==="confirm" && values.has("identity"),source_document_id:decision==="confirm" ? values.get("source") || null : null});
      else if(task==="reference") await post(`${base}/manuscripts/${id(values.get("manuscript"))}/references`,{idempotency_key:key(),span:{start:Number(values.get("start")),end:Number(values.get("end"))},markers:[values.get("marker")]});
      else if(task==="association") await post(`${base}/source-links`,{idempotency_key:key(),candidate_id:values.get("candidate"),reference_id:values.get("reference"),source_document_id:values.get("source") || null});
      else if(task==="source" || task==="manuscript") {const upload=new FormData(); upload.set("document",values.get("file")); if(task==="source") {upload.set("idempotency_key",key()); upload.set("metadata",JSON.stringify({title:values.get("title") || null,doi:values.get("doi") || null,year:values.get("year") ? Number(values.get("year")) : null,access_tier:values.get("tier")})); await auth.request(`${base}/sources`,{method:"POST",body:upload});} else {const parsed=await auth.request("/api/v1/documents/parse",{method:"POST",body:upload}); if(!current())return; await post(`${base}/manuscripts`,{idempotency_key:key(),filename:parsed.filename,media_type:parsed.media_type,text:parsed.text,blocks:parsed.blocks,parser_version:parsed.parser_version});}}
      if(current()) await load();
    });});
    content.addEventListener("click",e=>{const el=e.target.closest("button"); if(!el)return; const d=el.dataset; if(!d.extract && !d.references && !d.source && !d.run)return; action(async()=>{
      const token=generation,base=data.base,current=()=>!invalid && generation===token;
      if(d.extract || d.references) {await post(`${base}/manuscripts/${id(d.extract || d.references)}/${d.extract ? "extract-candidates" : "parse-references"}`,{}); if(current())await load();}
      else if(d.source) {const source=await auth.request(`${base}/sources/${id(d.source)}`); if(current())$("#source-inspector").innerHTML=`<h3>${esc(source.filename)}</h3><p>${esc(source.document_hash)} · ${esc(source.parser_version)}</p><pre>${esc(source.text)}</pre>`;}
      else if(d.run) {content.querySelectorAll("[data-run]").forEach(el=>el.disabled=true);const run=await auth.request(`${base}/audit-runs/${id(d.run)}`); if(!current())return; await runQueue(run.items,i=>post(`${base}/audit-runs/${id(d.run)}/items/${id(i.item_id)}/execute`,{idempotency_key:`execute-${i.item_id}`,input_snapshot_hash:i.input_snapshot_hash}),current,r=>report(`Item ${r.item_id}: ${r.status}${r.error_code ? " · "+r.error_code : ""}`)); if(current())await load();}
    });});
    try {
      await auth.start(); if(["signed_out","error"].includes(auth.currentState().kind)){clear("Choose Continue as guest or Sign in on the home page first.");return;}
      const owner=auth.currentState().userId;
      auth.onAuthStateChange?.(next=>{if(next.userId!==owner || ["signed_out","error"].includes(next.kind))clear();});
      controls.hidden=false;
      $("#project-create").addEventListener("submit",e=>{e.preventDefault();action(async()=>{const token=generation;const p=await post("/api/v1/projects",{idempotency_key:key(),name:$("#project-name").value});if(invalid || token!==generation)return;project=p.project_id;root.history?.replaceState(null,"",`/projects?project=${id(project)}`);await refreshProjects();await load();});});
      select.addEventListener("change",()=>{if(busy || invalid)return;project=select.value;root.history?.replaceState(null,"",project ? `/projects?project=${id(project)}` : "/projects");load().catch(e=>report(e.message));});
      $("#paper-refresh").addEventListener("click",()=>action(load));
      project=new URLSearchParams(root.location?.search || "").get("project") || "";
      await refreshProjects(); if(invalid)return; if(project)await load();else report("Choose or create a project. No provider calls are made by this view.");
    }catch(error){report(error.message);}
    return {clear};
  }
  function nextReview(rows,project) {const r=rows.find(r=>r.workflow_state==="review_pending" && r.audit_id);return r ? `/?audit=${id(r.audit_id)}&project=${id(project)}#result` : null;}
  const api={esc,renderCandidate,renderMapping,renderRow,renderMatrix,runQueue,pages,mount,nextReview};
  if(typeof module!=="undefined" && module.exports)module.exports=api;
  if(typeof document!=="undefined")mount(document,root.ClaimTrellisAuth);
})(typeof window!=="undefined" ? window : globalThis);
