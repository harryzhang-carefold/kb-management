# Changelog

## 2026-10-31

- Include current Authority-owned `documents` references with search hits, reusing the same native-cell/parsed-text identity serializer as discovery. Recheck membership/deletion before attaching metadata and links; never trust snippet-provided versions. Preserve retrieval routing, ranking, original hit content and existing source-read verification. Optional reference metadata respects the existing response bound and reports partial catalog coverage. This removes a missing-data reason for repeated discovery without prescribing an Agent workflow; internal-document permissions/native XLSX viewer remain separate unfinished T09 work. Seven new tests and eleven existing source-I/O tests pass (18/18). See `docs/t09-search-source-catalog-2026-10-31.md`; production performance still requires a same-goal live comparison.

- Remove serial I/O inside existing source operations without adding an Agent workflow: cross-KB `auto` and explicit `pageindex` searches run at most three independent authorized sources concurrently, each with its own database Session and copied request context. Keep the selected source set, query, engine, score ordering, tie order, top-k and partial-error behavior unchanged; explicit PageIndex still never falls back to vector search.
- Native XLSX citation verification now validates all requested evidence IDs and complete current-Invocation receipts before remote model checks, then checks independent claims in a bounded three-worker pool as the existing PageIndex verifier already does. Preserve every claim check, result order and `needs_review` failure; recheck source version and access after all checks before publishing. No cross-user cache, source-data changes, schema change or new tool.
- Add 11 isolated implementation tests for worker overlap, thread-confined Sessions, request-context propagation, ordering, failure isolation, complete-receipt preflight and final revocation. Run against previous source: 6 failures/5 passes; modified source: 11/11 passes. These are deterministic mechanism tests with fixture Authority/engines, not PostgreSQL integration or proof of real-model latency improvement. True authorized Provider comparison must follow the approved versioned deployment. Existing unrelated `tests/test_native_spreadsheet.py` work remains outside this change. See `docs/t09-independent-read-io-2026-10-31.md`.

## 2026-10-22

- Normalize each logical source page once when building its passage catalogue. Preserve passage IDs and duplicate grouping; avoid repeating whole-document Unicode/whitespace processing for every sentence during reads and citation checks.
- Preserve safe spreadsheet selector constraints in MCP invalid_input diagnostics, so range/filter mistakes can be corrected to a discovered table without dropping the requested filters.

- Document the existing deployment GitHub credential source and add a local push entry for origin/feat/pageindex. Read the authorized credential through SSH in memory, use a temporary askpass reference, and preserve local/global Git credential configuration.

## 2026-10-21

- Build all eight evidence-tool MCP argument contracts from the existing Authority models. Expose UUID/hash identities, read bounds, pagination limits and citation/filter limits before execution, without changing read authorization or continuation scope.
- Include each source's current parsed-text and native-cell document/version references in authorized PageIndex metadata. Read methods use their own exact reference pair; native queries prefer typed AND filters over complete matching rows while explicit range reads remain available.
- Add MCP argument-schema and source-reference regressions; preserve existing native XLSX parsing and evidence tests.

## 2026-10-13

- Support explicitly configured required equality-filter columns for native XLSX record queries. Expose the contract in discovered structure; reject incomplete selectors as MCP invalid_input with safe missing-column IDs. Keep unconfigured tables and raw range reading compatible; test real MCP HTTP rejection, typed AND reads and citations.

- Match equal XLSX numeric values across int/float storage representations without coercing text or booleans. Retain original types and test the actual MCP workflow with integral floating-point source cells.

- Keep XLSX text batches by actual worksheet/table/whole row with repeated headers and original coordinates. Only oversized rows become explicitly incomplete, losslessly reassemblable fragments. Validate stored offsets/hash before building; use existing editor region configuration without guessing headers or cross-row rules.
- Fix the actual MCP structure wrapper leaking a closure through locals(); test real HTTP discovery, structure, typed AND filtering and cell verification.
- Apply tree budgets to validated local trees and their composition separately; reject invalid retry trees. Bound model-build concurrency and retain source order to reduce long-document build latency.

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
