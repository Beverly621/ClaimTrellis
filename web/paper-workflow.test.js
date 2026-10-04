const assert=require("node:assert/strict");
const {test}=require("node:test");
const {renderCandidate,renderMapping,renderMatrix,runQueue,pages,mount,nextReview}=require("./paper-workflow.js");
const row={row_id:"link<&",candidate_id:"claim-1",reference_id:"ref-1",original_span:"Raw <span>",confirmed_claim:"Confirmed <claim>",citation:"<script>not executable</script>",source_document_id:"source<&",mapping_status:"confirmed",mapping_state_revision:1,workflow_state:"review_pending",evidence:[{text:"<img onerror='bad'>",locator:"p1",sha256:"hash"}],raw_relation:"supports",policy_status:"review_required",policy_reasons:["scope <mismatch>"],service_errors:[],human_decision:null,audit_id:"audit<&",proposal_version:1};
test("matrix escapes all manuscript, citation and evidence content",()=>{const html=renderMatrix({rows:[row],total:1,counts:{review_pending:1}},"project<&");assert.doesNotMatch(html,/<script>|<img onerror/);assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;claim&gt;/);assert.match(html,/&lt;img/);assert.match(html,/audit=audit%3C%26&project=project%3C%26/);});
test("raw supports never becomes policy or human acceptance",()=>{const html=renderMatrix({rows:[row],total:1,counts:{review_pending:1}},"p");assert.match(html,/<td>supports<\/td>/);assert.match(html,/review_required/);assert.match(html,/No human decision/);assert.match(html,/review_pending/);assert.doesNotMatch(html,/paper score|trustworthiness|auto.accepted/i);});
test("multisource matrix has stable distinct link identities and accessible table headers",()=>{const html=renderMatrix({rows:[row,{...row,row_id:"second",source_document_id:"second-source"}],total:2,counts:{review_pending:2}},"p");assert.match(html,/data-row="second"/);assert.match(html,/data-row="link&lt;&amp;"/);assert.equal((html.match(/scope="col"/g)||[]).length,9);assert.match(html,/<caption>/);assert.match(html,/2 shown \/ 2 total/);});
test("unmapped rows never expose a run checkbox or fabricated audit",()=>{const html=renderMatrix({rows:[{...row,workflow_state:"source_unmapped",source_document_id:null,audit_id:null}],counts:{source_unmapped:1},total:1},"p");assert.match(html,/Unmapped/);assert.doesNotMatch(html,/selected-link|Open ordinary audit/);});
test("filter counts are workflow counts and sorting does not change row identity",()=>{const html=renderMatrix({rows:[row,{...row,row_id:"later",workflow_state:"audit_pending"}],total:2,counts:{review_pending:1,audit_pending:1}},"p","review_pending","workflow");assert.match(html,/1 shown \/ 2 total/);assert.doesNotMatch(html,/data-row="later"/);assert.match(html,/audit_pending: 1/);});
test("candidate form preserves original exact span separately and requires human rubric",()=>{const html=renderCandidate({candidate_id:"c",status:"pending",source_sentence:"Sentence <x>",original_span:"Clause <y>",exact_span_start:0,exact_span_end:8,sha256:"h",state_revision:0,extraction_warnings:[]});assert.match(html,/Sentence &lt;x&gt;/);assert.match(html,/<blockquote>Clause &lt;y&gt;/);for(const n of ["atomic","faithful","necessary_context"])assert.match(html,new RegExp(`name="${n}"`));assert.match(html,/name="reviewer"/);assert.match(html,/name="notes"/);});
test("mapping confirmation explicitly requires uploaded source and identity declaration",()=>{const html=renderMapping({...row,mapping_status:"pending"},[{source_document_id:"s",filename:"<unsafe>.pdf",metadata:{title:"Study"},document_hash:"123456789012345"}]);assert.match(html,/name="identity"/);assert.match(html,/name="source"/);assert.match(html,/&lt;unsafe&gt;\.pdf/);assert.match(html,/Confirm identity/);});
test("queue caps concurrency at two and skips completed/running/unsafe items",async()=>{let active=0,peak=0,calls=0;const done=[];await runQueue([{status:"completed"},{status:"running"},{status:"failed",retry_allowed:false},...Array.from({length:5},(_,n)=>({status:"pending",n}))],async i=>{active++;peak=Math.max(peak,active);calls++;await new Promise(r=>setTimeout(r,5));active--;return {...i,status:"completed"};},()=>true,r=>done.push(r),20);assert.equal(peak,2);assert.equal(calls,5);assert.equal(done.length,5);});
test("quota-blocked result stops unscheduled calls, preserving partial completed items",async()=>{const calls=[];await runQueue([0,1,2,3].map(n=>({n,status:"pending"})),async i=>{calls.push(i.n);return {status:"quota_blocked"};},()=>true,()=>{},1);assert.deepEqual(calls,[0]);});
test("transport failure stops unscheduled calls and drains the other in-flight worker",async()=>{
  const calls=[],renders=[];let release,settled=false;
  const gate=new Promise(resolve=>release=resolve),error=new Error("network failed");
  const queue=runQueue([0,1,2,3].map(n=>({n,status:"pending"})),async i=>{
    calls.push(i.n);if(i.n===0)throw error;await gate;return {...i,status:"completed"};
  },()=>true,r=>renders.push(r.n));
  const observed=queue.then(()=>assert.fail("must reject"),e=>{assert.equal(e,error);settled=true;});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[0,1]);assert.equal(settled,false);
  release();await observed;assert.deepEqual(calls,[0,1]);assert.deepEqual(renders,[1]);
});
test("quota stop precedes a delayed render so the other worker cannot schedule a new call",async()=>{
  const calls=[];let release;const gate=new Promise(resolve=>release=resolve);
  const queue=runQueue([0,1,2].map(n=>({n,status:"pending"})),async i=>{
    calls.push(i.n);return {status:i.n===0 ? "quota_blocked" : "completed"};
  },()=>true,async r=>{if(r.status==="quota_blocked")await gate;});
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[0,1]);release();await queue;assert.deepEqual(calls,[0,1]);
});
test("result rendering failure also stops unscheduled requests",async()=>{
  const error=new Error("renderer failed"),calls=[];
  await assert.rejects(runQueue([0,1].map(n=>({n,status:"pending"})),async i=>{
    calls.push(i.n);return {status:"completed"};
  },()=>true,()=>{throw error;},1),e=>e===error);assert.deepEqual(calls,[0]);
});
test("identity change discards late item result and schedules nothing further",async()=>{let current=true;const calls=[],renders=[];await runQueue([0,1,2].map(n=>({n,status:"pending"})),async i=>{calls.push(i.n);current=false;return {status:"completed"};},()=>current,r=>renders.push(r),1);assert.deepEqual(calls,[0]);assert.deepEqual(renders,[]);});
test("persisted matrix pagination does not silently omit later rows",async()=>{const paths=[];const result=await pages({request:async path=>{paths.push(path);const offset=Number(new URL(path,"http://local").searchParams.get("offset"));return {total:201,rows:Array.from({length:offset?1:200},(_,n)=>({row_id:offset+n})),counts:{audit_pending:201}};}},"/api/v1/projects/p/matrix",()=>true);assert.equal(result.rows.length,201);assert.equal(paths.length,2);});
test("next pending review reuses the existing ordinary audit console",()=>{assert.equal(nextReview([{...row,workflow_state:"accepted"},row],"p"),"/?audit=audit%3C%26&project=p#result");assert.equal(nextReview([],"p"),null);});
function fakeDocument(){const nodes=Object.fromEntries(["paper-status","paper-content","project-controls","project-select","project-name","project-create","paper-refresh"].map(n=>[`#${n}`,{innerHTML:"",textContent:"",value:"",hidden:true,addEventListener(){},setAttribute(){},querySelectorAll(){return [];}}]));return {nodes,querySelector:s=>nodes[s]};}
test("signed-out page requests no protected data and never creates a guest",async()=>{const doc=fakeDocument();await mount(doc,{start:async()=>{},currentState:()=>({kind:"signed_out"}),request:()=>assert.fail("protected request")});assert.match(doc.nodes["#paper-status"].textContent,/Choose Continue as guest/);assert.equal(doc.nodes["#paper-content"].innerHTML,"");assert.equal(doc.nodes["#project-controls"].hidden,true);});
test("cross-tab logout or account switch clears cached project data and discards late response",async()=>{for(const next of [{kind:"signed_out",userId:null},{kind:"permanent",userId:"other"}]){const doc=fakeDocument();let listener,release,began;const gate=new Promise(r=>began=r);const pending=mount(doc,{start:async()=>{},currentState:()=>({kind:"permanent",userId:"original"}),onAuthStateChange:cb=>listener=cb,request:()=>{began();return new Promise(r=>release=r);}});await gate;doc.nodes["#project-name"].value="private draft";listener(next);release([{project_id:"secret-id",name:"secret name"}]);await pending;assert.doesNotMatch(doc.nodes["#project-select"].innerHTML,/secret/);assert.equal(doc.nodes["#project-name"].value,"");assert.equal(doc.nodes["#paper-content"].innerHTML,"");assert.match(doc.nodes["#paper-status"].textContent,/session changed/);}});
