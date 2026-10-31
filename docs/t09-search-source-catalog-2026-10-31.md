# T09: reuse current source references after search

## Observed problem

Fresh authorized natural questions on Agent `76b595d` and KB `4d7d892` took N1 **63.982s** and N2 **64.147s** end-to-end. Private traces `34c0afa5-98c6-4707-9865-82e1a06dcc2f` and `80926588-7f68-42a5-ab28-e93f7bf5ac07` show successful `search_knowledge` followed by further whole-catalog discovery before reading an already-hit document. N1 records 16 model calls, 10 tools and one tool error; N2 records 13 models, eight tools and one error. Source retrieval and final response work remain expensive; context compression in these two cold sessions was only around 5 milliseconds, not the older long-session 27-second bottleneck.

Search hit snippets did not include the actual published native-cell/parsed-text reference pairs needed by the existing reader. The Agent therefore had to rediscover them. This change does not introduce a workflow, force a route, narrow the user's scope, cache permission or interpret snippets as verified facts.

## Changes

- Share one `document_reference` serialization between authorized `knowledge_discover` and document metadata lookup.
- `search_knowledge` includes a deduplicated `documents` catalog of the hit documents' current Authority-owned original ID, canonical source ID, file type, title, native-cell/parsed-text reference pairs and available readers. The original `items`, retrieval modes, scoring and requested hit set remain unchanged, except documents no longer authorized or deleted after search are excluded.
- The existing document lookup rechecks current KB membership. No source identity comes from search snippet metadata. Source reads still reauthorize and verify source version/hash. Reference links use the existing permitted link mechanism; the independent `internal` tagging/canAccessKnowledge feature is **not** implemented by this change.
- Optional catalog entries are omitted, with `source_catalog_complete=false`, if they would push an otherwise fitting search beyond the existing 64,000-character contract; requested search hits are not silently removed to fit metadata. Normal authorized discovery remains available for omitted references.
- The Agent's existing evidence/parameter-binding adapter consumes `/documents` through a declared companion `catalogPath`. Its original search `source` evidence policy and semantic review remain unchanged. Metadata does not count as a complete read or checked citation, and does not create a persistent Procedure Run or automatic next-tool scheduler.

## Verification

Five source-catalog regression tests failed against the prior implementation, then passed. Two additional tests cover shared source-pair identity and bounded optional metadata. Together with existing source fanout and citation parallelism regressions, **18/18** isolated implementation tests pass; Python compilation and whitespace checks pass. Agent bindings tests prove canonical parameters are reusable, while failed or legacy snippet-only search cannot invent bindings and catalog metadata cannot acquire checked citation status.

These are mechanism tests, not live performance acceptance. Record deployed revisions and real Provider follow-up results separately. Preserve the unrelated worktree modification in `tests/test_native_spreadsheet.py`; do not publish synthetic business documents or alter membership/data.
