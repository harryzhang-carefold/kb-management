# T09: remove avoidable search-model requests in the existing source engine

## Baseline and scope

Agent remains at `eb48d47df86a760889059c08b16ef21f71635f8d`; the rejected public read-plan executor and window-default experiment are not reinstated. Knowledge Module baseline is `d60e23bc4117d78d89da678bc74839aa18e4eef7`.

The same authorized natural questions were repeated before this change, with new SaaS Provider sessions and no prescribed tools:

| Case | User total / first text | Models / tools / errors | Private Trace |
| --- | --- | --- | --- |
| N1: short meaning/source for Reason Code 197 | 41.424s / 40.616s | 8 / 6 / 1 | `d32bcf8e-ffd8-4e33-ab31-3c4969763d53` |
| N2: brief status-code/reason-code distinction and source, no statistics | 62.062s / 61.781s | 8 / 7 / 0 | `8fa9a2ac-7118-4191-b6d2-c4fb5eb9656d` |

N1 had an actual verifier-input error; it remains in the denominator. N2 spent about 36.760s in Agent models and 23.301s in tools. Public HTTP200/completion is not an independent answer-quality or latency acceptance.

## Changes inside existing source operations

### Auto retrieval: literal source candidates before unnecessary semantic selection

The existing PageIndex tree and original full text already support lexical ranking. For auto retrieval only, return original source candidates without another model request when the returned excerpt has at least three matching query tokens, at least 0.75 query-token coverage, and every numeric qualifier (including one-digit identifiers). Stale or invalid offsets, weak overlap, synonyms and matches only beyond the returned excerpt keep the existing semantic selector. Selection is generic and contains no Claim Code, source name, KB UUID, workflow vocabulary or user-phrase routing.

Rank specific matching ranges before encompassing parent ranges and deduplicate them. Keep equally matching documents as candidates; do not turn the first hit into an entity decision. Metadata says `selected_by=lexical_candidate` and `score_source=lexical_coverage`, never `checked` or semantic support. The ordinary authorized, current-version reading/complete-passage receipts and semantic citation verifier still establish final source claims. Explicit PageIndex mode retains semantic selection; explicit vector/keyword/hybrid modes and index construction are unchanged.

### Small homogeneous PageIndex scopes: one engine call, not one LLM per KB

The MCP auto entry calls the same tree engine over the bounded pure-PageIndex subset of the supplied authorized KB set. Remaining mixed/embedding KBs retain their original engines and are merged exactly once; no authorized KB is omitted. The grouped subset must fit the existing 50-document tree bound. Larger scopes, failed joint retrieval and inventory growth fall back to the original bounded per-KB paths.

The initial all-or-nothing grouping in `b373818` was deployed with healthy API/worker/MCP. Natural N1/N2 measured **35.177s / 88.276s**, compared with **41.424s / 62.062s** before. Logs confirmed zero selection-model calls in the exact-code KB but separate semantic calls in other pure PageIndex KBs: an embedding KB had prevented joint optimization of the whole set. This was an incomplete optimization, not proof of overall improvement. The subset correction adds actual MCP merge/non-duplication tests (65 relevant tests total) and retains this slow sample. The original query, source IDs, user request context and tool schema are unchanged. No cross-user cache, alternate executor, durable job or mandatory task workflow is introduced.

A multi-KB inventory that grows after composition is checked returns `grouping_unavailable` before truncating; no later KB is silently dropped. A model-written document prefix must resolve uniquely in the actual source set, never to the first ambiguous or empty-prefix match.

### JSON format fallback: preserve real failure causes

`LLMClient.chat` previously caught every exception as an unsupported JSON format, then made another model request without `response_format`. Timeout, unauthorized, rate-limit, server failure and unrelated invalid input therefore received an unjustified second request. Only HTTP400 explicitly naming the format parameter or unsupported-format code now triggers this compatibility retry. Original errors and the existing outer recovery path remain intact; no raw provider exception is logged by this fallback. Six fixtures reproduce five failures before the correction and verify the retained genuine format fallback.

## Validation

Tests exercise actual functions with isolated adapters. Coverage includes literal/semantic branches, source filters, staleness, numeric qualifiers, ambiguous IDs, large/mixed scopes, inventory change, same source/query propagation, main MCP joint selection and fallback, original retrieval prefilter, parsing/tree partition, source reauthorization and existing parallel-source behavior. Existing tests are unchanged; the unrelated local `tests/test_native_spreadsheet.py` modification is neither edited nor staged. Local tests run in an isolated temporary environment using locked top-level dependencies; production dependency files are unchanged.

These are mechanism tests, not proof of real Provider speed or broad retrieval quality. After versioned deployment, rerun N1/N2 with unchanged questions, inspect actual search and model times, check source-read/citation identities, then retain all repeated samples including errors. No p95 claim follows from a handful of runs.

## Actual release location, verified before publishing

The original `/home/harry.zhang/kb-management` worktree is on another branch with unrelated pending work. It must not be reset, cleaned or overwritten. Current API/worker/MCP user services run from `/home/harry.zhang/kb-releases/d60e23b`, an existing detached release worktree. Existing releases link `backend/.venv` and `infra/.env` to the established deployment resources; nginx mounts the existing primary checkout's `02-development/deploy/dist`.

Publication uses `scripts/push_upstream.py` to the approved `feat/pageindex`. Prepare the next exact-commit worktree through the existing shared Git repository, preserve the established environment links and frontend mount, then run that commit's versioned `scripts/deploy_runtime.sh`. Do not copy modified source files into a running service, alter Agent Actions, replace credentials or touch other people's source/test artifacts. Verify service WorkingDirectory/HEAD and API/MCP readiness after deployment.

T09 remains open for stable end-to-end latency, actual answer quality, internal-document access policy and original XLSX deep links. This change only targets avoidable source-search model requests and an erroneous compatibility retry.
