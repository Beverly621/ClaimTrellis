# Privacy and data handling

## Local-first default

Parsing, chunking, retrieval, deterministic checks, SQLite persistence, and reports run on
the local machine by default. No document is uploaded merely by opening the interface.
In hosted mode, uploaded source bytes are sent to the ClaimTrellis service for in-memory
parsing; they are not persisted as raw files.

## Provider transmission

When the default Jev adapter is configured with `TYPESAFE_API_KEY` and the user initiates
an audit, the service transmits:

- the atomic claim;
- one selected evidence set of one to three source passages (at most 8,000 source characters);
- the minimum citation/source metadata needed for interpretation;
- the versioned question definitions.

When a reviewer explicitly requests a revision, the request additionally includes their
feedback, the previous structured proposal and policy reasons, deterministic checks,
source completeness, and parent/version references. Feedback is untrusted review context,
not replacement source evidence. Reviewer aliases are recorded locally, not included in
the provider's revision context.

It does not transmit a separate full-manuscript field. A short source can fit entirely in
the selected passages. Users must review TypeSafe's current
terms and institutional rules. Zero-data-retention requirements need an appropriate
provider agreement; the open-source software cannot create that agreement.

## Persistence and anonymous identity

Local mode stores audit records in SQLite. Hosted mode stores owner-scoped audit records,
candidate and selected evidence, feedback, proposal versions, revision runs, text-free
block locator/hash manifests and audit events in PostgreSQL. Raw PDF/DOCX/TXT/MD bytes
and an additional full parsed-source copy are not persisted. Retained candidate passages
can contain all text of a short source; treat the entire record as potentially sensitive.
Hosted provider usage rows record the owner ID, a secret-keyed HMAC of the canonical
requester IP, audit ID for revisions, provider, operation, status, timestamps, optional
token counts, and a sanitized error code. They do not store the raw IP, claim, evidence,
provider key, or upstream error body. The HMAC secret is server-only and is not logged.
The server verifies a Supabase access token and uses its user ID as the record owner.
When Account Access v1 is enabled and a permanent user explicitly syncs their account,
`user_profiles` may store only the server-verified email, verification status,
authentication method and account timestamps. Product updates opt-in defaults to false.
Guest users do not need to provide an email.
The browser's Supabase session storage grants access to that anonymous identity; clearing
browser data, signing out or switching devices before account linking can make the
workspace inaccessible. Account linking preserves the same user ID; histories are never
automatically merged across different identities. Retention and deletion tools are not yet
implemented. Database paths, uploaded documents, caches and local reports are ignored
by Git.

## Paper Workflow retention (P1.1–P1.3)

The opt-in `/api/v1/projects` backend stores normalized manuscript text, its complete
grounded blocks, original candidate spans, human-confirmed claim text, bibliography
excerpts, links and append-only workflow events (including reviewer aliases, notes and
rubric attestations). P1.3 also retains the full normalized text and blocks of uploaded
SourceDocuments, supplied metadata, parser version and text hash. Raw uploaded file bytes
are not stored as application records. This is a separate collection, not a change to ClaimAudit's minimum
snapshot retention above. Text persists to support repeatable exact-span extraction.
Owners are derived from verified identity, never from request JSON; every child lookup
checks both owner and project. PostgreSQL tables have RLS enabled and no grants for
`anon` or `authenticated`; server-side owner scoping remains mandatory.

No Paper Workflow request in P1.1–P1.3 sends data to Jev or creates an audit. No retention
expiry, deletion API or browser workflow UI is implemented by these stages. Treat project
text and events as sensitive retained records and do not upload confidential material.
Supplied source metadata and parsed bibliography metadata are unverified descriptions,
not proof of paper identity. Human identity decisions and text hashes are stored separately.

## Paper orchestration and browser projection (P1.4–P1.5)

An explicitly executed, human-confirmed claim/source pair creates an ordinary ClaimAudit
under the same owner. Its selected evidence is sent to the configured provider only when
provider evaluation is explicitly selected, available and atomically budget-reserved.
Planning, Matrix projection and human claim/source decisions do not call a provider.
Runs/items retain immutable input identities/hashes, confirmed claim text, operational
state, attempts and audit association. Recovery checkpoints additionally retain the ordinary
audit snapshot and typed provider result (not a second paper-level judgment). Usage records
retain sanitized outcome codes and token counters through the existing audit/provider
records; hosted usage retains only the existing HMAC IP identifier, never raw IPs or keys.
No expiry/deletion policy is introduced: these are sensitive retained records.

The authenticated browser view includes normalized source/manuscript text, original
reference/claim spans, evidence, reviewer notes and event history. It clears its in-memory
view and pending selections on logout/account change and ignores stale responses. It does
not put project text, audit data or reviewer drafts into browser local storage. Operators
must approve a retention/deletion policy before confidential real-world use.

## Offline retrieval and acceptance (P1.6–P1.7)

Retrieval experiments use a locally downloaded, pinned embedding model, CPU and an
in-memory exact index. They never send paper text to an embedding API or replace the
production retriever. The first model download contacts the public model registry;
do not attach private Hub credentials unnecessarily. Source snapshots, queries, qrels,
embeddings and per-query results may contain manuscript/source text. Keep private data
and local output in Git-ignored directories, with operator-controlled access. Supplied
real-paper labels remain human annotations, not model-created gold data.

Browser/database acceptance uses invented repository-licensed fixtures and explicit
Supabase/Jev test doubles against disposable databases. An opt-in live smoke creates one
ordinary Guest and two invented ClaimAudits under normal hosted retention and quota;
it does not read the owner's browser session or expose the server key. It logs out that
throwaway session but does not delete its stored records or any real user data. Sanitized
local reports contain model versions and usage, never tokens/keys/configuration files.
Live smoke and owner real-paper testing are integration checks, not approval for
sensitive data or accuracy validation. Hosted Provider remains enabled by the owner's
latest decision; this PR changes no hosted configuration or quotas.

## Sensitive data

Do not process protected health information, personal data, confidential peer-review
material, or embargoed research until the operator has documented legal basis, retention,
access, deletion, incident response, and provider processing terms.
