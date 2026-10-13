> Current XLSX implementation (2026-10-13): local openpyxl extraction with row-aware bounded PageIndex text batches. XLSX does not require MinerU. Native cell evidence is separate; see [原始 XLSX 契约](native-spreadsheet-evidence.md). The earlier proposed MinerU XLSX route below is historical, not an implementation instruction.

# 文档解析策略设计（Parsing Strategy）

> 版本：v2.0（MinerU 统一解析架构，已按用户决策定稿，进入实施）
> 决策：**复杂文档解析统一使用 MinerU**（本地 CPU 部署），覆盖 PDF / DOCX / PPTX / XLSX / 图片。
> 原则：能用 MinerU 统一解决的不再维护多套解析器；纯文本类（TXT/MD/HTML）走本地轻量路径，零额外开销。

---

## 0. 现状与目标

### 当前实现（`backend/app/utils/doc_parser.py`）

| 类型 | 现状 | 问题 |
|------|------|------|
| PDF | `pypdf` 逐页 `extract_text()` | 无结构、丢层级、双栏乱序、扫描件直接报错 |
| DOCX | `python-docx` 取段落 + 表格 | 未保留标题层级、表格用 ` \| ` 拼接无行列语义 |
| TXT / MD | 直接 decode | 无问题 |
| HTML | `BeautifulSoup` 取文本 | 无结构 |
| Excel / PPT / 图片 | ❌ 不支持 | `detect_file_type` 无对应分支 |

### 数据流（现状）

```
MinIO 原始文件
   → parse_document(data, file_type) → full_text（纯文本，无结构）
   → chunk_text()（按 \n\n 段落切分，500 字/50 重叠）
   → embedding（gte-qwen2, 3584d）→ Elasticsearch
```

### 核心矛盾

1. **解析丢结构**：标题层级、表格行列关系在解析阶段被压平。
2. **chunker 破坏表格**：按段落切分会切断 Markdown 表格。
3. **能力缺口**：Excel、PPT、图片无法入库。

### 目标

- **MinerU 统一解析**：PDF / DOCX / PPTX / XLSX / 图片 全部走 MinerU，输出 LLM-ready Markdown（保留标题层级 + 表格 + 公式）。
- **TXT / MD / HTML**：本地轻量解析（纯 CPU，毫秒级），不经过 MinerU（MinerU 官方不支持 HTML 输入）。
- **chunker 升级**：表格不可分割 + 表头重复 + 标题绑定。
- **性能与上限**：CPU 部署，PDF 上限下调至 15MB（≈300 页），其他类型 50MB。

---

## 1. MinerU 部署方案（本地 CPU）

### 1.1 部署形态

- **Docker 容器**，加入 kb-net 网络，`127.0.0.1:9030:8000`（FastAPI 解析接口）。
- **自定义 CPU 镜像**（官方镜像默认面向 GPU）：

```dockerfile
FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-core fonts-noto-cjk fontconfig libgl1 \
    && fc-cache -fv && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install -U 'mineru[core]' 'mineru-vl-utils'
# 模型首次启动时自动下载（MINERU_MODEL_SOURCE=modelscope/huggingface），缓存到 /models
ENV MINERU_MODEL_SOURCE=modelscope
ENTRYPOINT ["bash", "-c", "mineru-api --host 0.0.0.0 --port 8000 --backend pipeline && exec \"$@\""]
```

- **纯 CPU 运行**：`--backend pipeline`（layout + OCR 规则流水线，不需要 VLM 大模型），`MINERU_DEVICE_MODE=cpu`。
- **模型体积**：~2GB（layout + det + rec + ocr 等小模型），挂载卷 `kb_mineru_models:/models` 持久化，只下载一次。
- **资源**：建议预留 8GB 内存；`--shm-size 4g`。

### 1.2 接口

```
POST {MINERU_API_URL}/file_parse
  form: files=<二进制>  (可多文件)
        backend=pipeline
        lang_list=ch
        return_md=true
  response: JSON 数组，每项含 markdown 字符串、页码、表格、图片等结构化结果
```

**官方原生支持的输入格式**：PDF、图片（JPG/PNG/BMP/WebP/TIFF）、DOCX、PPTX、XLSX。
**不支持**：HTML、TXT、MD → 本地解析。

### 1.3 性能预期（CPU，pipeline 后端）

| 文档类型 | 预期耗时 | 说明 |
|---------|---------|------|
| 简单文本 PDF（10 页） | 30s ~ 2min | layout 检测 + 文本提取 |
| 复杂 PDF（表格/双栏，50 页） | 5 ~ 15min | OCR + 表格还原 |
| XLSX（10 sheet × 500 行） | 1 ~ 3min | 表格转 Markdown |
| PPTX（30 页） | 1 ~ 3min | 逐页 layout + 文本 |
| 图片（单张扫描件） | 20 ~ 60s | OCR |
| DOCX（50 页） | 30s ~ 2min | 原生 DOCX 解析（3.0+ 端到端） |

> 解析在 Celery 异步任务中进行，不阻塞 API 响应。前端已有「解析中」轮询。

---

## 2. 解析路由（Router）

```
上传文件
  │
  ├─ 扩展名 ∈ {txt, md, markdown, html, htm} → 本地轻量解析（现有逻辑，保留）
  │
  └─ 扩展名 ∈ {pdf, docx, pptx, xlsx, xls, jpg, jpeg, png, bmp, webp, tiff}
        → MinerU /file_parse（pipeline backend, lang_list=ch）
        → 提取 markdown 正文
        → 注入 front-matter 元数据
```

### 2.1 新增文件类型（file_type 枚举扩展）

| 旧 | 新 |
|----|----|
| pdf, docx, md, txt, html | pdf, docx, pptx, xlsx, txt, md, html, jpg, png, bmp, webp, tiff |

- `xls`（老格式）：上传时若检测到 `.xls`，提示用户另存为 `.xlsx`（MinerU 不支持 xls），返回 40001。
- 图片统一映射：`jpg/jpeg → jpg`，其余按扩展名。

### 2.2 文件大小限制

| 类型 | 上限 |
|------|------|
| pdf | **15 MB**（CPU 解析时长保护，约 300 页内） |
| docx / pptx / xlsx | 20 MB |
| 图片 | 20 MB |
| txt / md / html | 10 MB |

（现有 `rag_max_file_size_mb` 全局值拆分为按类型配置，写入 settings。）

---

## 3. 统一输出规范

所有解析器统一返回 **Markdown 字符串 + meta 字典**：

```markdown
---
source_type: pdf
source_name: 财务手册.pdf
page_count: 12
parse_engine: mineru-pipeline
parsed_at: 2026-09-21T10:00:00Z
---

# 一级标题
## 二级标题

正文段落...

| 列A | 列B |
|---|---|
| a1 | b1 |
```

- `Document.full_text`：存 **纯 Markdown 正文**（不含 front-matter），chunker 直接处理。
- `Document.meta`（新增 JSONB 字段）：存 front-matter 内容（parse_engine、page_count、source_type 等）。
- MinerU 返回的中间 JSON（表格坐标、图片引用）不入库，仅取 markdown。
- 图片文档：若 OCR 无文字，meta 标注 `ocr_text_empty: true`，正文为占位说明（仍入库，检索时低召回是预期行为）。

---

## 4. 后端改造

### 4.1 新模块结构

```
backend/app/parsing/
  __init__.py
  router.py        # parse_document(data, filename) → (markdown, meta)
                   # 扩展名判定 → 本地解析 or MinerU 调用
  local_parsers.py # TXT / MD / HTML（迁移自 utils/doc_parser.py 现有逻辑）
  mineru_client.py # MinerU API 客户端（httpx，超时 30min，重试 1 次）
                   # 健康检查 /health（GET / 或 /file_parse 405 探测）
```

- 现有 `utils/doc_parser.py` 保留为兼容入口，内部委托 `parsing/router.py`；`workers/tasks.py` 调用方式不变。
- MinerU 不可用时：文档置 `failed`，error_message 明确提示「解析服务不可用」，**不降级**（避免质量不一致；用户可「重新解析」重试）。

### 4.2 MinerU 客户端

```python
# app/parsing/mineru_client.py
MINERU_API_URL = settings.mineru_api_url          # http://127.0.0.1:9030
MINERU_BACKEND = settings.mineru_backend          # pipeline
MINERU_TIMEOUT = settings.mineru_timeout_seconds  # 默认 1800s

def parse_with_mineru(data: bytes, filename: str) -> tuple[str, dict]:
    """POST /file_parse，返回 (markdown, meta)。失败抛 ParseError。"""
```

- `httpx` 已在依赖中，无需新增 HTTP 库。
- 超时 30min（CPU 大文件），单文档解析在 Celery 内串行完成。
- meta 提取：从响应中取 `page_count`、`backend`、各页 markdown 拼接。

### 4.3 chunker 升级（`services/chunker.py`）

结构感知切分：

1. **解析 Markdown 结构块**：标题段（`#...`）、完整表格（连续 `|` 行）、代码块（```）、普通段落。
2. **表格不可分割**：表格 ≤ chunk_size → 整块保留；> chunk_size → 按行切，**每块重复表头 + 分隔行**。
3. **标题绑定**：标题与其后第一个内容块绑定（标题孤立在块尾时并入下一块头部）。
4. 兼容 `chunk_size=500 / overlap=50` 参数，仅改变切分边界。
5. front-matter（若存在）单独剥离，不进入 chunk（meta 已存 `Document.meta`）。

---

## 5. 数据模型变更

| 变更 | 说明 |
|------|------|
| `document.file_type` CHECK 约束 | 扩展为 12 种（§2.1） |
| `document.meta` JSONB（新增列，默认 `{}`） | 存解析元数据 |
| `Document.meta` ORM 字段 | 同步 |

**迁移方式**（项目无 alembic 迁移历史，沿用直连 PG 方式）：
1. `ALTER TABLE document DROP CONSTRAINT ck_doc_filetype;`
2. `ALTER TABLE document ADD CONSTRAINT ck_doc_filetype CHECK (file_type IN (...));`
3. `ALTER TABLE document ADD COLUMN meta JSONB DEFAULT '{}'::jsonb;`
4. 同步更新 `infra/init_db.sql`（供新环境重建）。

---

## 6. API 变更

| 接口 | 变更 |
|------|------|
| POST `.../documents`（上传） | 接受新文件类型；按类型校验大小上限；`file_type` 映射新枚举 |
| GET `.../documents/{id}` | 响应增加 `meta` 字段（DocOut 扩展） |
| GET `.../documents/{id}/content` | 不变（full_text 现为 Markdown，前端用 `marked` 渲染） |
| GET `/system/parse-engine` | **新增**（admin）：MinerU 服务健康检查 `{status, backend, model_source, latency_ms}` |
| GET `/system/monitor` | services 增加 `mineru` 状态 |

**前端变更**（KbDetailView.vue）：
- `accept` 与 `beforeUpload` 白名单扩展为：`.txt .md .html .htm .docx .pdf .pptx .xlsx .jpg .png .bmp .webp .tiff`
- 上传提示文案同步更新
- 「查看」弹窗：内容用 `marked` 渲染 Markdown（项目已依赖 `marked`），保留原文/渲染切换

---

## 7. 实施清单（按依赖顺序）

1. `infra/docker-compose.yml` 新增 `mineru` 服务 + `infra/.env`（MinerU 配置）
2. `app/core/config.py`：`mineru_api_url / mineru_backend / mineru_timeout_seconds / 按类型大小上限`
3. `app/models/models.py` + PG 迁移 SQL + `infra/init_db.sql` 同步
4. `app/parsing/` 新模块（router + local_parsers + mineru_client）
5. `app/services/chunker.py` 结构感知升级
6. `app/api/documents.py`（上传校验）+ `app/api/system.py`（parse-engine/monitor）+ schemas
7. 前端 `KbDetailView.vue` 白名单 + Markdown 渲染
8. 构建、重启、端到端验证（见 §8）

---

## 8. 验证方案（端到端）

| # | 用例 | 预期 |
|---|------|------|
| 1 | MinerU 健康检查 `GET /system/parse-engine` | status=ok，latency 合理 |
| 2 | 上传 .xlsx（多 sheet 含中文表头） | 解析为 `## Sheet: x` + Markdown 表格；chunk 不切断表格 |
| 3 | 上传 .pptx（10 页） | 每页标题 + 文本按页入库 |
| 4 | 上传 .jpg（含中文文字的扫描件） | OCR 文本提取成功，meta.page_count=1 |
| 5 | 上传复杂 PDF（双栏 + 表格，<15MB） | 层级标题保留，表格还原为 Markdown 表格 |
| 6 | 上传 .txt / .md | 走本地解析，秒级完成（不经过 MinerU） |
| 7 | 上传 .xls | 40001，提示转 .xlsx |
| 8 | 上传 20MB PDF | 41301 文件过大 |
| 9 | 停止 MinerU 容器后上传 PDF | 文档 failed，error 提示解析服务不可用；重启后「重新解析」成功 |
| 10 | 检索验证：对 xlsx 表格列值提问 | 混合检索能命中表格 chunk，RAG 回答正确 |

---

## 9. 风险与权衡

| 风险 | 缓解 |
|------|------|
| CPU 解析慢，大 PDF 接近超时 | 上限 15MB + 30min 超时 + 失败可重试；后续可挂 GPU 机器提速 |
| MinerU 模型下载失败（网络受限） | 构建镜像时预下载（构建机可访问 HF/modelscope 则 bake 进镜像）；卷持久化避免重复下载 |
| 内存占用（pipeline 峰值 ~4-6GB） | 容器 limit 8GB；本机资源紧张时与其他服务错峰 |
| 扫描件 OCR 质量 | lang_list=ch 中文优化；质量差时用户可用更清晰源文件重新解析 |
| chunker 改造影响旧数据 | 新逻辑仅对新文档生效；旧文档可「重新解析」重建 |
| MinerU 输出图片引用（本地路径） | 入库前清理 markdown 中失效的图片相对路径（MinerU 输出目录在容器内，KB 侧不可访问），保留 alt 文本 |
