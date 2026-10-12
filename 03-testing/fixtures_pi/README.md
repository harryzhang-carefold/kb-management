# fixtures_pi — 默认索引方式改 pageindex 的独立验证夹具

本目录夹具由测试工程师（云天明）**自行编写**，不复制 `05-temp/` 或历史 `testdata/` 中的旧夹具。
用于验证改动卡 t_7f451c5f / commit 3dc1ddf：上传文档默认索引方式 embedding → pageindex。

版本：PI-V1　生成时间（UTC）：2026-10-12 03:24　分支：feat/default-pageindex

## 夹具清单

| 文件 | 用途 | 唯一 token | 字节数 | 字符数（含标题）| 正文段落字符数 | sha256 |
|---|---|---|---|---|---|---|
| `pi_default_doc.md` | 默认上传（**不传 index_type**）应为 pageindex；树检索问答应能命中正文 token | `PI-TOKEN-7412` | 2129 | 777 | 646 | `11321dc6870f37b6f4ab895937ee4074af6db19a2db607cccb729cd1a809a0a7` |
| `emb_regression_doc.md` | 显式 `index_type=embedding` 回归，确认向量链路不受默认值变更影响 | `EMB-TOKEN-8251` | 596 | 210 | 209 | `ad8bc0fb9722bba8611bdd98c211912420278abaccb1136fe72c0aa790dbf51d` |
| `legacy_no_index_type_doc.md` | 模拟"历史无 index_type"文档（DB 侧 meta 去掉 index_type），确认仍按 embedding 兜底、不被排除 | `LEG-TOKEN-6390` | 587 | 207 | 206 | `c3257bbe446e14425a9eeeb392041434cb64983595ea41cf8f3195847880b985` |

## 结构要点（供用例判定）

- `pi_default_doc.md`
  - H1 标题 1 个，标题层级为 **1/2/3 三级**（≥2 层），含 2 个**不相关干扰小节**：「附则（干扰小节）」「术语表（干扰小节）」。
  - 唯一口令 `PI-TOKEN-7412` 出现在**正文段落**中（§2.2 班中抽检与异常上报），**不是**只出现在标题里；树检索/问答命中该 token 才算真命中正文。
  - 正文段落字符数 646（规格要求 600~1000）。
- `emb_regression_doc.md` / `legacy_no_index_type_doc.md`：纯文本（无 markdown 标题），字符数 210 / 207（规格要求 200~400）。

## 复核方式（可重放）

```bash
cd /home/harry.zhang/kb-management
sha256sum 03-testing/fixtures_pi/*.md
backend/.venv/bin/python <measure script> 03-testing/fixtures_pi   # 字符数/token 位置/层级 自检
```

## 使用约束（后续用例卡务必遵守）

- 只上传到**自己新建的、名字带 `VI-PI` 前缀 + 时间戳**的测试 KB；不得改动既有 KB / 文档。
- `pi_default_doc.md` 上传时**不要**显式传 `index_type`（要测的就是默认值）；`emb_regression_doc.md` 上传时显式传 `embedding`。
- `legacy_no_index_type_doc.md` 需按用例 5 的做法，在上传后于 DB 侧将 `meta.index_type` 删除以模拟历史文档（**只对本卡新建文档**，不得改他人文档）。
- 夹具内容一旦改动，sha256 变化，本 README 与后续报告须同步更新（sha256 = 入参指纹的一部分）。
