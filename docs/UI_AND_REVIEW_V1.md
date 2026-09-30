# UI Design v1 and human-governed proposal revisions

This is the owner's scoped v0.1 freeze exception, not a new provider or relation taxonomy.
Six source relations remain provider judgments. Accept, reject, revise and defer are
human lifecycle actions, never alternate relation labels.

## Data and lifecycle

`ClaimAudit` adds current proposal ID/version, `review_status`, and `state_revision`.
`ProposalVersion` retains an immutable judgment/policy snapshot, probabilities, provider
metadata, parent reference and creation time. Its lifecycle status is stored separately;
status updates never overwrite the original snapshot. `RevisionRun` retains each request,
feedback, idempotency key, status, result reference and sanitized failure metadata.
`judgment_summary` is optional and empty for Jev: policy reasons are not model reasoning.

- Initial proposal: `pending_review`.
- Accept: `accepted`, a terminal human-confirmed version.
- Reject: `rejected`; no provider call. A revision may follow.
- Defer: `deferred`; later review or revision is allowed.
- Revise: `revision_requested` → `revision_running` → new `pending_review` version.
  The parent becomes `superseded`, or remains `rejected` if previously rejected.
- Failure: `revision_failed`; preserve the old judgment and feedback, do not create a
  verdict or a new version. A new request/key retries the failed evaluation.

Provider calls are bounded to 90 seconds. On a subsequent record/history read, a pending
attempt older than 180 seconds is marked interrupted, so process termination does not
leave an audit permanently running. There is no background worker or synthetic progress.

## API and concurrency

Existing audit, parsing, retrieval, health, CLI and uvicorn entrypoints remain available.
OpenAPI describes the added typed schemas automatically.

| Endpoint under `/api/v1/audits/{audit_id}` | Contract |
| --- | --- |
| `POST /reviews` | `decision`, `notes`, `reviewer`, proposal ID/version and expected state revision |
| `POST /revisions` | `feedback`, `reviewer`, proposal ID/version, expected state revision, idempotency key |
| `GET /proposals/current` | Latest proposal snapshot with lifecycle status |
| `GET /proposals` | All snapshots in version order |
| `GET /revisions` | All attempts, including failed requests |
| `GET /events` | Append-only timeline in insertion order |

Mutations use SQLite transactions and compare-and-swap on the current proposal and state
revision. A stale tab, competing action or conflicting idempotency payload gets HTTP 409.
Only one revision can be active per audit. Repeating the same key and payload returns the
existing attempt without a second provider call. A completed/failed request is returned
as HTTP 200 with a typed `RevisionRun.status`; clients must inspect that status. The first
request awaits the provider while separate GET requests can observe actual lifecycle events.

## Provider contract

`evaluate(claim, evidence, citation, *, revision_context=None)` adds optional context.
First evaluations retain the original question set. Revisions use
`claim-source-revision-en-v1` and supply the original evidence plus the previous proposal,
deterministic checks, source completeness, human feedback and version reference. Explicit
instructions treat feedback as information to check, never authoritative evidence.

No hidden chain-of-thought is requested or displayed. The TypeSafe integration follows
its typed-judgment interface; Jev does not generate a narrative explanation. Other existing
implementations of the provider protocol must accept the optional keyword to support revisions.

## Events

Creation records `audit.created`, `source.loaded`, `checks.completed`, `proposal.created`.
Human actions record `feedback.recorded` and `review.accepted`, `review.rejected` or
`review.deferred`. Revisions record `feedback.recorded`, `revision.requested`,
`revision.started`, then `revision.failed` or `proposal.superseded` (when applicable),
`proposal.created`, `revision.completed`. New events reference audit and proposal ID/version.
Feedback, reviewer, parent and provider/error metadata accompany the relevant event.

## UI workflow and design references

The landing page leads into an actual source-upload console, not a simulated dashboard.
Evidence, checks, probabilities and provenance sit alongside a permanent human-feedback
panel. Revision uses the real endpoint, polls persisted events, compares versions and
returns to human review. Previous versions remain read-only. Failure offers retry;
conflicts refresh the record and retain the user's text. No scientific performance is claimed.

The original visual system combines editorial scale and composition inspired by
[Landbook](https://land-book.com/) and [Awwwards](https://www.awwwards.com/), thread/grid
and sticky-stack patterns explored through [React Bits](https://reactbits.dev/) and
[21st.dev](https://21st.dev/), and section storytelling informed by
[MotionSites](https://motionsites.ai/). All HTML, CSS, JS and SVG here are original;
no external component code, fonts, assets or runtime dependencies were copied or added.
Motion can be paused and respects reduced-motion preferences; mobile layouts are stacked,
keyboard focus is visible and the relation explorer supports arrow/Home/End keys.

## Migration and limits

Back up SQLite before upgrade. Initialization adds `proposal_versions` and `revision_runs`,
backfills legacy audits with one version and appends a clearly marked migration event.
Existing events are never edited or deleted. Historical events may lack proposal references.
Unversioned legacy `/reviews` requests work only on untouched v1 records; after any action,
clients must reload and send explicit references. The old `revise` action now returns 409
instructing clients to use `/revisions`, rather than silently pretending a provider reran.
Legacy deterministic-only human reviews remain readable and compatible; the new UI does
not offer semantic acceptance when no provider judgment exists.

The original v1 implementation's concurrency guarantees required all requests to share
one SQLite database; Vercel `/tmp` storage was neither durable nor shared across instances.
That local mode remains single-user. Downgrade a local v1 database by restoring a backup,
not by deleting lifecycle tables.

## Hosted storage and history extension

The original SQLite path above remains the local compatibility mode. Hosted mode instead
uses PostgreSQL with an explicit schema migration and verified Supabase anonymous user
ownership. Each mutation locks the owner-scoped audit row, checks proposal/state revision,
updates the lifecycle and appends events in one transaction. Unique revision idempotency
and one-active-revision constraints live in the database. Provider calls occur after the
request/start transactions commit, never while a row lock is held. Event and revision
ordering use database sequences. Proposal snapshots remain immutable; lifecycle status
changes are stored separately. This preserves the six relation labels, four human actions,
provider inputs and original revision semantics.

The browser restores/creates its anonymous session before protected requests. The recent
ledger and `/history` use owner-scoped API results, while `/?audit=<id>#result` restores
the selected record after refresh. A missing or other-user ID returns 404. Local mode is
single-user; hosted mode requires both PostgreSQL and Supabase Auth. Production migration
and environment configuration are explicit operator steps, not automatic deploy behavior.

## UI v1.1 refinement

The owner-requested v1.1 pass keeps the v1 information architecture and backend contract.
It reduces the dominant surface to claim, source, selected evidence, proposal and human
action. Deterministic checks, policy rationale, proposal history and provenance use native
disclosures; lifecycle summary is separate from the complete append-only audit view.

The typography system has four roles: bold system grotesk for display, neutral system sans
for controls and body UI, Georgia as a restrained editorial serif for evidence and research
guidance, and system mono only for IDs, versions, locators, timestamps and probabilities.
Near-black, paper white and neutral gray dominate. The cool accent is reserved for focus,
selected evidence, current proposals and primary actions. No font, component or runtime
dependency was added.

A single accessible guidance dialog serves evidence, relation, check, action and timeline
help. Its warm paper treatment distinguishes the research handbook from the instrument UI.
The native dialog supports Escape, focus restoration and backdrop dismissal; on mobile it
becomes a bottom sheet. The compact mobile navigation and all added help controls meet a
44-pixel touch target. Reduced-motion behavior remains unchanged.

The API still requires non-empty notes for all four human actions. The refined UI communicates
that Revise and Reject need substantive feedback while Accept and Defer can use a short note;
it does not weaken or misrepresent the current validation contract.
