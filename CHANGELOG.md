# Changelog

## 2026-10-13

- Fix PageIndex partitioning for sections longer than the input limit: use bounded splits when no heading fits, retain all source text and contiguous offsets, and cover Unicode and mixed short/long sections.

- Parse XLSX text locally with the same original-cell parser instead of requiring MinerU. Keep the upload default PageIndex and the selected text-index type; native cell evidence remains a separate path.

- Classify typed evidence validation/access failures as MCP invalid_input/forbidden without exposing rejected values or relying on error-text matching.

- Make the versioned deployment stop duplicate legacy systemd units only when their ExecStart belongs to this exact checkout; prevent an old unit from reclaiming port 9012 during release.

- Add authorized collection/document discovery and native XLSX structure, bounded cell reads and citation verification to the existing 9100 service. Keep all ten existing tools and parsed-text/PDF retrieval paths.
- Preserve original types, coordinates, merges, formula/cache status and source/config/parser versions. Publish native snapshots independently; failed builds and queueing retain existing text/index evidence.
- Add editor-only table/header configuration and explicit existing-source rebuild management. Keep Agent knowledge access read-only.
- Validate native cell workflows, actual PostgreSQL membership, current-Invocation receipts, source changes and full Unicode continuation; prohibit PageIndex SDK/PDF use in the native path.

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
