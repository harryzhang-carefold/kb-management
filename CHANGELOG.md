# Changelog

## 2026-10-12

- Use purple PageIndex method tags in document lists, search results and document previews; keep failure status red. Adopt existing successful text indexes into evidence without changing their uploaded files or directory trees.

- Fix queued/parsed/embedding status polling after upload and reparse, and restart polling after an index rebuild. Keep the last successful index until replacement publication; explicit rebuild requests bypass the indexing cache.

- Merge the deployed auto-retrieval and citation fixes before extending `feat/pageindex`.
- Integrate the independent Carefold PDF/OCR/version/evidence implementation into the existing 9100 MCP service. Preserve the six KB tools and web retrieval routes.
- Parse PDFs locally without a mandatory MinerU service. Preserve physical pages, exact passages, source revisions, continuous bounded reading and Invocation-scoped citation checks.
- Keep originals and OCR PDFs in MinIO, versions and delivery receipts in PostgreSQL, and processing files in temporary workspaces. Bound recovery caches; reclaim deleted document versions, objects and full text.
- Enforce actual KB account ownership/membership for all MCP source access. Require explicit Runtime Actor bindings; reject unverified JWT-shaped strings.
- Pin one compatible API/worker/MCP dependency environment and expose document links with physical-page navigation.
- Validate PDF/OCR ingestion, real MCP HTTP, access denial, revision changes, receipt isolation, lossless Unicode pagination and deletion against an isolated PostgreSQL database.
