# Local ERP Agent context

The authenticated gateway binds a user and tenant to a queued event. The worker
revalidates the principal, establishes the tenant scope and builds a context
frame before making a tool decision. The frame has four layers.

| Layer | Data source | Use |
| --- | --- | --- |
| Conversation | Durable user-and-tenant memory and pending workflow | Resolve recent references and preserve clarification state |
| Company | Tenant profile, currency and effective tax rules | Interpret domain language and select relevant policy |
| Financial and operational state | Scoped live records, fiscal periods and budget envelopes | Check prerequisites and identify missing or competing facts |
| Identity | Authenticated event, live principal and tool permissions | Filter memory and retrieval and authorize every tool invocation |

Memory stores bounded record IDs. The worker resolves them again against the
current tenant and permissions. Timeout and stale lease rollback leave the prior
memory intact. Reset deletes memory for the current user and tenant. Model inputs
are immutable snapshots assembled before inference. Inference threads have no
database access. Tenant records and embeddings stay out of shared model artifacts.

For customer, invoice and stock follow-ups, local character similarity ranks
short utterances against examples for read-only actions. Recent record type and
explicit record nouns constrain the candidates. An unfamiliar substantive word
or competing interpretation stops automatic record reuse. Related reads check
both permissions and resolve each side of the relationship inside the company.
An invoice with multiple matching products asks the user to select an item.
Confirmed writes use the authenticated confirmation endpoint, with locked
revalidation of the original preview.

Phase 1 uses existing ERP services for commercial actions and introduces
context-conditioned reading, entity search and preview flows. Phase 2 adds
invoice audit and live tax and budget checks, plus PostgreSQL concurrency and
isolation coverage. In both phases, the database transaction owns the tool result,
conversation update and append-only audit record.
