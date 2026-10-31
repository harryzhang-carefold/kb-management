# Changelog

## 2026-10-31

- T09 source-search latency: auto PageIndex retrieval now returns explicitly labeled original-text lexical candidates without a model selection call only for strong visible overlap (at least three query tokens, 0.75 coverage, all numeric qualifiers). Weak/stale/ambiguous literal signals retain the existing semantic selector; explicit PageIndex and other explicit retrieval modes remain unchanged. Candidates are never checked answers. The current authorized source-read/receipt and citation verifier still establish every published knowledge claim.
- Small homogeneous authorized PageIndex KB sets now share one existing tree-engine request rather than one model request per KB. Mixed/large sets, inventory growth and joint failures retain the original isolated source paths. No source/query rewriting, cross-Actor cache, new executor, fixed business flow or index conversion. Reject empty/ambiguous model-written document prefixes instead of selecting the first source.
- Correct JSON compatibility fallback: only a provider-declared unsupported response format (HTTP400) retries without that parameter. Timeouts, authentication errors, rate limits, server errors and unrelated bad inputs preserve their actual error instead of silently creating a duplicate model request. Tests reproduce five failed cases before the fix.
- Relevant retrieval/parse/source-isolation/JSON tests **63/63 pass**, py_compile and diff check pass. These are mechanism tests, not a live latency claim. Fresh Agent eb48d47 / KB d60e23b natural baselines are N1 **41.424s**, N2 **62.062s**; actual errors are retained. Use the current versioned KB release worktree, not the unrelated dirty original checkout. See `docs/t09-source-search-latency-2026-10-31.md`; post-deploy same-question traces and independent quality checks remain required. The pre-existing `tests/test_native_spreadsheet.py` modification stays untouched and unstaged.

- Add stable citation verifier `reason_code` values (`checked`, `claim_not_supported`, `source_text_mismatch`, `location_not_unique`, `verifier_timeout`, `verifier_unavailable`, `verifier_truncated`) while preserving the existing bounded human-readable reason. PageIndex and XLSX evidence outputs propagate the code; callers that still return only the legacy `supported/reason` shape remain compatible through a deterministic fallback code. This lets the Agent distinguish “omit or read new evidence” from verifier infrastructure failures without parsing free text or upgrading `needs_review` to checked. Verifier/search/PageIndex/XLSX contract regressions **45/45 pass**. Existing unrelated `tests/test_native_spreadsheet.py` changes remain unstaged. Deployment and natural N2 verification are required before claiming fewer verification retries.

- Publish a bounded native-XLSX structure summary with the current versioned evidence pointer and derive it read-only from the exact stored version for existing documents. The summary exposes only configured sheet/table/column selectors, counts and completeness; it excludes cell values, formulas, merged ranges and raw rows. `pageindex_list_documents` and `search_knowledge` now tell callers to use a complete current summary directly and call `spreadsheet_get_structure` only for missing/partial structure or unlisted raw ranges. No table, filter or business choice is made by Runtime. New structure/catalog tests plus PageIndex/search/evidence regressions **42/42 pass**. Existing unrelated `tests/test_native_spreadsheet.py` changes remain unstaged. Deployment and natural N2 verification are still required before claiming fewer model rounds.

- Bound PageIndex LLM selection without replacing semantic judgment. A deterministic lexical pass now narrows only strong-overlap queries (`matched >= 4` and coverage `>= 0.35`) to each document root plus at most 64 deduplicated source nodes; weak-overlap queries keep the complete outline. The LLM still selects the final node, authorization/source identity are unchanged, and no task/KB/query string is hard-coded. Read-only production diagnostics predict N2’s 603/1004-node outlines shrink to at most 65 nodes (about 89.2%/93.5%) while its weak first search remains unchanged. Candidate mode/counts are logged without query or source text. PageIndex/search/evidence regressions 36/36 pass. This is not a latency claim until the exact revision is deployed and natural N2 is repeated. Existing unrelated `tests/test_native_spreadsheet.py` changes remain unstaged.

- Make the search-hit source catalog contract explicit: `source_catalog_scope=returned_hits` and `source_catalog_complete=true/false` distinguish a complete catalog for returned hits from a bounded partial catalog, without claiming the whole Knowledge Base was enumerated. The search tool contract tells callers to reuse current authorized source identities for native reads and broaden discovery only for missing, stale, partial or full-directory goals. PageIndex/XLSX citation tools now ask for concise user-facing claims that Runtime may display directly only after checked, while unsupported explanation remains outside the claim. Contract tests 17/17 pass. PostgreSQL integration suites require an isolated `kb_migration_test`; the local service was unavailable on port 9011, so those 19 tests were not executed and are not reported as passed. Existing unrelated `tests/test_native_spreadsheet.py` changes remain unstaged and outside this commit.

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
