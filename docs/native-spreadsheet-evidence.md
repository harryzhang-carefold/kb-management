# 原始 XLSX 证据与业务作业接入

在现有 9100 MCP 上增加四个只读工具，原有十个工具保持名称、参数和返回兼容。

1. `knowledge_discover`：不指定 kb_id 时按 offset/limit 返回已授权集合；指定实际 kb_id 返回候选文档、版本及 read_methods。`evidence.parsed_text` 与 `evidence.native_cells` 是两条不同的读取凭据，使用各自实际 document_id/version。
2. `spreadsheet_get_structure`：无 sheet_id 时发现工作表；指定真实 sheet_id 时分页读表格/合并区域；再指定实际 table_id 时分页读列。不能从空表头猜业务字段。
3. `spreadsheet_read_cells`：指定真实 sheet_id，选择 cell_range 或已发现 table_id；列条件支持 eq、contains 与 AND。数字和文本编号保持区别，公式缓存缺失时不能作为已知值过滤。正文按签名 cursor 完整续读，scope、原始文件、版本与筛选绑定；工作表序号只在内部使用，输出没有合成 PDF 页。
4. `spreadsheet_verify_citations`：提交本次完整读取的 evidence_id、sheet_id、cell_range 和 claim。返回真实 cells locator，定位与内容支持分别记录。跨 Invocation、撤权、过期或未读完不能核验。

原生单元格解析使用固定的 openpyxl==3.1.5，**不调用 PageIndex SDK，不转 PDF**。原有 XLSX 文本索引继续工作，但它不等于原始单元格证据。版本包含文件哈希、实际解析器版本与表格配置。原生快照独立发布 `spreadsheet_evidence`；失败保留之前成功指针，不修改全文、旧树或索引类型。

XLSX 上传默认仍为 PageIndex。文本提取在本地使用 openpyxl，随后进入原有 PageIndex/Embedding 文本索引路径，按上传时实际选择执行。它不依赖旧 MinerU 服务，不因增加原生单元格能力而自动切换为 Embedding；单元格读取和定位始终独立于 PageIndex SDK。


| 用途 | 读取方式 |
| --- | --- |
| 发现适用文档、理解整体内容 | PageIndex 文本索引 |
| 查询业务规则 | 发现真实工作表、区域、列定义，联合筛选并读取完整记录 |
| 定位及核验依据 | 原始 XLSX 单元格证据 |

例如 Reason Code 197，先取得实际列及类型，再同时筛选 `Code Type = Reason Code` 和 `Code = 197`；读取匹配整行的解释、适用范围、处理步骤与例外，不能仅凭编号找到一格解释。

文本建树输入按工作表 → XLSX 自带表格或显式配置区域 → 完整行组织。每批重复工作表、区域、真实表头/列坐标；正文保留行号及单元格坐标。只在一行本身超过单批上限时拆分，标记同一行、分段序号/总数及字符范围，`row_complete=false`；拼回全部分段才构成完整记录。未配置区域明确为原始区域、无表头。缺失坐标代表空白，不猜继承；跨行业务关联需源文档明确的结构或管理员配置。

解析器保存全文哈希和连续批次边界，建树器校验后直接使用，不按字符二次切断行。修改区域配置后，通过已有重新解析入口生成对应文本索引；原生重建仍独立。旧解析正文继续兼容，选择性重解析不改变文件或索引类型。

分片独立通过原有树深度/节点预算；合并树增加一个文档根层，组合预算按分片数计算，不能把合法分片误判降级。无效的首次树及重试树不发布。建树请求有界并发（`PAGEINDEX_BUILD_CONCURRENCY`，默认 4，范围 1–8），合并仍按原文顺序，线程不接触数据库；可设 1 以适配模型服务限流。单片超时、失败和既有降级状态保持明确。

管理员可调用 PUT `/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/spreadsheet-config`，body 为 `[{"id":"actual-table","sheet":"实际工作表","range":"A1:F100","header_row":1}]`；权限至少 editor，所有值来自实际文件与业务配置。POST 同一路径的 `/spreadsheet/rebuild` 重建。新上传/重解析 XLSX 自动排队补充原生证据；原生队列失败不使原有文本解析失败。

对已有文档，管理员在已批准的版本化 checkout 中执行：

```sh
backend/.venv/bin/python scripts/build_spreadsheet_evidence.py --document-id <实际已授权 XLSX UUID>
```

命令不新增文档，也不重建旧文本索引。只处理明确给出的文档，不自动批量修改线上所有文件。不存在表头配置时保留范围读取，等待管理员确认。

业务操作接口由 SaaS 后端同事提供。此仓库不保存理赔/人员/跟进状态，不把文档代码解释当作患者事实。Agent 保存知识来源 Procedure Run，Runtime 执行权限、Schema、预算及恢复；客户结果与内部流程引用分开。

验收使用隔离 PostgreSQL `kb_migration_test`，测试中的合成文件仅放在本地 mock object store。线上仅使用获授权的既有资料或用户明确要求上传的真实文档，不添加合成验收文档，不清理同事已有未提交文件。部署固定 commit，再使用 `scripts/deploy_runtime.sh`；不要修改运行源码代替版本发布。

Release order: stop this Knowledge Module's MCP (9100), API (9012), worker and duplicate launchers from the same checkout, update the approved version and dependencies, then start and verify. Port 9100 stays the MCP endpoint; port 9012 stays the HTTP API. No new service port is introduced. Preserve unrelated units and uncommitted files.
