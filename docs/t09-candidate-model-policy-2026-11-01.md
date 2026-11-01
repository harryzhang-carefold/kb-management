# T09: explicit generation policy for search candidates (2026-11-01)

## Scope and hypothesis

This changes only the existing PageIndex retrieval node-selection model request. It does not change the Agent executor, query, authorized KB set, lexical/semantic routing, original file/index, source-read receipts, independent citation support checker, OCR or indexing/build model settings.

The live model is deepseek-flash and the candidate selector previously omitted the thinking setting. The official provider contract documents thinking enabled/high as the default and supports an explicit thinking.type=disabled through the OpenAI SDK's extra_body. Verified 2026-11-01: https://api-docs.deepseek.com/guides/thinking_mode/ and https://api-docs.deepseek.com/api/create-chat-completion/ . These are API capabilities, not latency measurements or proof of candidate quality.

The existing LLMClient accepts optional typed thinking=True/False/None. Only known DeepSeek model contracts receive the wire switch; arbitrary compatible endpoints keep the prior request. Existing callers that omit the option (including index construction) remain unchanged. The existing PageIndex candidate call uses the configuration pageindex_retrieve_disable_thinking; false restores the prior provider default. The deployed test default for this experiment is true. Citation checking uses its own existing client/request and is deliberately unchanged.

A returned candidate still cannot be published as a checked answer. Actual current authorized reading and independent source-support verification remain required. The same retry, original-source identity validation, candidate ranking, ambiguity and fallback rules remain in place. No source/Actor cache, task classifier or fixed workflow is added.

## Validation

Nine new tests reproduced eight failures before implementation and now pass, covering enabled/disabled/omitted/unsupported model settings, genuine JSON-format compatibility retry, original request/scope preservation, and zero extra model requests on the existing strong-literal path. Retrieval, source/catalog, parallel-source, verifier and argument-schema suites pass (79 non-database cases in the combined run).

An isolated local PostgreSQL instance was created with a temporary database named kb_migration_test, randomized loopback port and temporary password, never a production database. The combined 90-case run reports 88 passed, one OCR-environment skip and one failure: test_mcp_http_preserves_tools_and_authenticated_evidence expects a JSON-RPC error member for invalid arguments, but the currently installed MCP stack returns a different envelope. Running the same unmodified test against a clean temporary export of baseline 18b64de reproduces the exact KeyError at line 208. This is a pre-existing HTTP-error contract mismatch, not a passing check and not a new candidate-mode regression. No test expectation was weakened. Both temporary databases and temporary baseline source were removed after testing.

Production dependencies and the original unrelated modification of tests/test_native_spreadsheet.py are untouched. Python compile/diff checks pass. The local baseline HTTP mismatch remains a separately recorded outstanding issue.

## Release and measurement

Use only the already authorized feat/pageindex branch and that exact revision's scripts/deploy_runtime.sh in an isolated release worktree. Preserve the existing .venv/.env links, service user and frontend mount; never reset the dirty primary server checkout or change the Agent GitHub Actions workflow.

Measure after the separately released Agent pagination-provenance correction, keeping that Agent revision fixed. Use identical N1/N2 and unseen N3/N4 in fresh authorized SaaS sessions; record total/first-visible latency, actual model/tool/search/verification time, failures and source-grounded delivery. Repeat the batch and run positive/negative native row and internal-only privacy regressions. Roll back the model-mode change when it fails the comparison or harms evidence selection. A handful of requests cannot establish p95 or broad retrieval recall.

This remains an experiment until the real post-release results exist. T09 is still open for stable latency, internal-document viewing authorization and original XLSX cell deep links.
