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
- one selected evidence passage;
- the minimum citation/source metadata needed for interpretation;
- the versioned question definitions.

When a reviewer explicitly requests a revision, the request additionally includes their
feedback, the previous structured proposal and policy reasons, deterministic checks,
source completeness, and parent/version references. Feedback is untrusted review context,
not replacement source evidence. Reviewer aliases are recorded locally, not included in
the provider's revision context.

It does not transmit the entire manuscript by design. Users must review TypeSafe's current
terms and institutional rules. Zero-data-retention requirements need an appropriate
provider agreement; the open-source software cannot create that agreement.

## Persistence and anonymous identity

Local mode stores audit records in SQLite. Hosted mode stores owner-scoped audit records,
selected evidence, feedback, proposal versions, revision runs and audit events in
PostgreSQL. Raw PDF/DOCX/TXT/MD bytes and the full parsed source text are not persisted.
Hosted provider usage rows record the owner ID, a secret-keyed HMAC of the canonical
requester IP, audit ID for revisions, provider, operation, status, timestamps, optional
token counts, and a sanitized error code. They do not store the raw IP, claim, evidence,
provider key, or upstream error body. The HMAC secret is server-only and is not logged.
The server verifies a Supabase access token and uses the anonymous Supabase user ID as
the record owner. No email address is collected or stored by ClaimTrellis in this phase.
The browser's Supabase session storage grants access to that anonymous identity; clearing
browser data, signing out or switching devices before account linking can make the
workspace inaccessible. Account linking, retention and deletion tools are not yet
implemented. Database paths, uploaded documents, caches and local reports are ignored
by Git.

## Sensitive data

Do not process protected health information, personal data, confidential peer-review
material, or embargoed research until the operator has documented legal basis, retention,
access, deletion, incident response, and provider processing terms.
