# 原始 XLSX 证据与业务作业接入

在现有 9100 MCP 上增加四个只读工具，原有十个工具保持名称、参数和返回兼容。

1. `knowledge_discover`：不指定 kb_id 时按 offset/limit 返回已授权集合；指定实际 kb_id 返回候选文档、版本及 read_methods。`evidence.parsed_text` 与 `evidence.native_cells` 是两条不同的读取凭据，使用各自实际 document_id/version。
2. `spreadsheet_get_structure`：无 sheet_id 时发现工作表；指定真实 sheet_id 时分页读表格/合并区域；再指定实际 table_id 时分页读列。不能从空表头猜业务字段。
3. `spreadsheet_read_cells`：指定真实 sheet_id，选择 cell_range 或已发现 table_id；列条件支持 eq、contains 与 AND。数字和文本编号保持区别，公式缓存缺失时不能作为已知值过滤。正文按签名 cursor 完整续读，scope、原始文件、版本与筛选绑定；工作表序号只在内部使用，输出没有合成 PDF 页。
4. `spreadsheet_verify_citations`：提交本次完整读取的 evidence_id、sheet_id、cell_range 和 claim。返回真实 cells locator，定位与内容支持分别记录。跨 Invocation、撤权、过期或未读完不能核验。

原生单元格解析使用固定的 openpyxl==3.1.5，**不调用 PageIndex SDK，不转 PDF**。原有 XLSX 文本索引继续工作，但它不等于原始单元格证据。版本包含文件哈希、实际解析器版本与表格配置。原生快照独立发布 `spreadsheet_evidence`；失败保留之前成功指针，不修改全文、旧树或索引类型。

XLSX 上传默认仍为 PageIndex。文本提取在本地使用 openpyxl，随后进入原有 PageIndex/Embedding 文本索引路径，按上传时实际选择执行。它不依赖旧 MinerU 服务，不因增加原生单元格能力而自动切换为 Embedding；单元格读取和定位始终独立于 PageIndex SDK。

管理员可调用 PUT `/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/spreadsheet-config`，body 为 `[{"id":"actual-table","sheet":"实际工作表","range":"A1:F100","header_row":1}]`；权限至少 editor，所有值来自实际文件与业务配置。POST 同一路径的 `/spreadsheet/rebuild` 重建。新上传/重解析 XLSX 自动排队补充原生证据；原生队列失败不使原有文本解析失败。

对已有文档，管理员在已批准的版本化 checkout 中执行：

```sh
backend/.venv/bin/python scripts/build_spreadsheet_evidence.py --document-id <实际已授权 XLSX UUID>
```

命令不新增文档，也不重建旧文本索引。只处理明确给出的文档，不自动批量修改线上所有文件。不存在表头配置时保留范围读取，等待管理员确认。

业务操作接口由 SaaS 后端同事提供。此仓库不保存理赔/人员/跟进状态，不把文档代码解释当作患者事实。Agent 保存知识来源 Procedure Run，Runtime 执行权限、Schema、预算及恢复；客户结果与内部流程引用分开。

验收使用隔离 PostgreSQL `kb_migration_test`，测试中的合成文件仅放在本地 mock object store。线上仅使用获授权的既有资料或用户明确要求上传的真实文档，不添加合成验收文档，不清理同事已有未提交文件。部署固定 commit，再使用 `scripts/deploy_runtime.sh`；不要修改运行源码代替版本发布。

Release order: stop this Knowledge Module's MCP (9100), API (9012), worker and duplicate launchers from the same checkout, update the approved version and dependencies, then start and verify. Port 9100 stays the MCP endpoint; port 9012 stays the HTTP API. No new service port is introduced. Preserve unrelated units and uncommitted files.
