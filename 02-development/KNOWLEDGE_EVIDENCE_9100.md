# Unified Knowledge service

The existing KB site, API, Celery pipeline, MinIO and PostgreSQL remain authoritative.
The 9100 MCP server retains its six KB tools and adds the four Carefold evidence
tools. PDF uploads with `index_type=pageindex` automatically parse and index through
the native PDF/OCR pipeline. Other document formats retain their existing parsers
and expose their parsed text without invented PDF coordinates.

Install `backend/requirements.lock.txt` in the single `backend/.venv`. Install
Tesseract language data for the configured `PAGEINDEX_OCR_LANGUAGES` (default
`eng+chi_sim+chi_tra`). Apply
`infra/migrations/20261012_knowledge_evidence.sql` to the existing database; the
same schema is included in `infra/init_db.sql` for a new installation. Restart
the API, Celery worker and MCP services from their versioned launch scripts.

Set `KB_MCP_API_KEY` to an independent secret of at least 32 bytes, and configure
`KB_MCP_ORGANIZATION_ID`, `KB_MCP_AGENT_DEFINITION_IDS` and
`KB_MCP_ACTOR_BINDINGS` in `infra/.env`. Bind an authenticated Runtime Actor to
an existing KB username; the binding does not bypass that account's ownership
and membership. Use `forwardInteractionScope=true` and
`forwardCallerAuthorization=false` in the Agent MCP connection. A SaaS JWT is
not a KB service credential. Configure a scope signing secret at both ends if
the Runtime deployment requires signed Actor authorization.

The original upload is referenced directly in MinIO. An OCR PDF, if required,
is stored under `pageindex/{document_id}/{version}/processed.pdf`. PostgreSQL
retains exact versioned page text and trees. Delivery receipts expire after one
hour, recovery caches retain at most 4096 entries per kind and seven days.
Temporary original/OCR/SDK files are removed when their operation ends. Retained
source versions are intentional evidence history; deletion removes all versions,
receipts, MinIO objects, SQL chunks and full text for that document. Storage
still grows with retained uploads and versions, so monitor MinIO/PostgreSQL and
host capacity. A PageIndex worker does not maintain a second permanent archive.

To backfill an existing PageIndex PDF, use the site's rebuild/reparse action.
Reparse PDFs that previously failed before text extraction. The new evidence
catalog only exposes documents with a successful current evidence version.

Regression command (use an isolated database named `kb_migration_test`):

```sh
PG_DB=kb_migration_test python -m pytest -q tests/test_knowledge_evidence.py
```

Retire the old 9383 service only after a real KB upload reaches `indexed`, the
Provider conversation calls 9100, and its Trace shows complete reading and
citation verification. Keep pre-existing source data intact until its migration
has been confirmed; stopping a duplicate service is not permission to erase data.
