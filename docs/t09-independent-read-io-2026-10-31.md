# T09: bounded independent source I/O, not a new Agent workflow

## Observed production problem

With Agent revision `76b595d`, the same natural read-only questions were replayed through the authorized SaaS Provider. N1 took 50.456 seconds; N2 took 115.270 seconds. Their private Trace final-answer hashes match the public test reports. N2 Trace `b9d5c450-c087-479b-b345-003e3baa0a91` records 11 model calls and 14 actual tools with no tool error; two searches cost 34.492 seconds and four spreadsheet verification calls cost 22.930 seconds. The response has four current-Invocation checked citations, but latency remains unacceptable. Context compression was only 6.717 milliseconds in this sample, not the older 27-second blocker.

## Existing source implementation changed

- `_auto_search` and `_pageindex_search` retain their existing engines and requested source sets. The independent source requests now overlap at a maximum of three workers. Every worker creates/closes its own SQLAlchemy Session and receives a distinct copy of the request context. Results are consumed in original source order before the unchanged stable score sort/top-k. No selected scope is broadened or narrowed, no query is rewritten, and no alternate retrieval mode is introduced.
- `SpreadsheetService.call` keeps complete receipt validation, evidence ID/coordinates, source identity and typed operation validation. It validates the entire requested citation batch before starting model I/O. Independent semantic support checks then overlap with the same three-worker policy as existing PageIndex evidence verification. Unavailable/invalid/unsupported checks remain `needs_review`. Source version and permissions are checked again after all workers finish; changed/revoked data cannot publish checked citations.
- No new execution tool, persistent Run, semantic scheduler, shared user data cache, backend authorization grant, or business-specific branch is created. Agent Runtime and source APIs retain their existing contracts.

## Validation and limits

New tests use the actual function/method AST compiled verbatim from the implementation, with isolated Authority, retrieval and Session adapters. They do not access production documents, PostgreSQL or MinIO. Tests cover bounded overlap, out-of-order completion, stable output order, ContextVar propagation, thread-confined Sessions, per-source failure, no implicit fallback, incomplete receipt denial before any check and final source/permission revocation.

The same tests run against the prior committed implementation in a temporary directory: **6 failures / 5 passes**. Current implementation: **11/11 pass**; `py_compile` and `git diff --check` pass. Existing unrelated `tests/test_native_spreadsheet.py` modifications are neither changed nor committed by this work.

These are mechanism regressions, not an independent full backend integration acceptance. Production performance, semantic accuracy, same-source evidence and error denominators must be rechecked using the authorized SaaS Provider after versioned deployment. A three-worker pool does not imply threefold end-to-end improvement; model load, single-source requests and sequential Agent decisions may dominate.

## Publication

Use existing `scripts/push_upstream.py` to publish the approved `feat/pageindex` commit. On the existing server checkout, verify no overlapping changes, fast-forward only to that exact commit, and execute the same commit's `scripts/deploy_runtime.sh`. Preserve all unrelated server artifacts and documents. Do not copy source files into the running service, reset dirty work or change the Agent deployment workflow. Record actual revision/health and post-release measurements rather than asserting future success.
