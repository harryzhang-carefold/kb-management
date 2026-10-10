# 知识库管理系统 — 数据模型与表结构

**版本**: v1.0
**数据库**: PostgreSQL 15
**向量/全文**: Elasticsearch 8.x

---

## 1. ER 图

```mermaid
erDiagram
    USER ||--o{ KNOWLEDGE_BASE : "owns"
    USER ||--o{ KB_MEMBER : "via"
    KNOWLEDGE_BASE ||--o{ KB_MEMBER : "via"
    KNOWLEDGE_BASE ||--o{ DOCUMENT : "contains"
    DOCUMENT ||--o{ CHUNK : "split_into"
    DOCUMENT ||--o{ PROCESS_TASK : "processed_by"
    USER ||--o{ CONVERSATION : "has"
    KNOWLEDGE_BASE ||--o{ CONVERSATION : "in"
    CONVERSATION ||--o{ MESSAGE : "contains"

    USER {
        uuid id PK
        varchar username UK
        varchar email UK
        varchar password_hash
        varchar role
        varchar display_name
        boolean is_active
        timestamp created_at
        timestamp updated_at
    }
    KNOWLEDGE_BASE {
        uuid id PK
        uuid owner_id FK
        varchar name
        text description
        varchar status
        int chunk_size
        int chunk_overlap
        int embedding_dim
        varchar embedding_model
        jsonb settings
        boolean is_deleted
        timestamp created_at
        timestamp updated_at
    }
    KB_MEMBER {
        uuid id PK
        uuid kb_id FK
        uuid user_id FK
        varchar role
        timestamp created_at
    }
    DOCUMENT {
        uuid id PK
        uuid kb_id FK
        uuid uploaded_by FK
        varchar filename
        varchar file_type
        bigint file_size
        varchar minio_key
        varchar status
        int chunk_count
        text full_text
        jsonb meta
        text error_message
        int version
        boolean is_deleted
        timestamp uploaded_at
        timestamp indexed_at
        timestamp created_at
        timestamp updated_at
    }
    CHUNK {
        uuid id PK
        uuid document_id FK
        uuid kb_id FK
        int chunk_index
        text content
        int token_count
        jsonb metadata
        timestamp created_at
    }
    PROCESS_TASK {
        uuid id PK
        uuid document_id FK
        varchar task_type
        varchar status
        varchar celery_task_id
        text result
        text error_message
        int retry_count
        timestamp started_at
        timestamp finished_at
        timestamp created_at
    }
    CONVERSATION {
        uuid id PK
        uuid kb_id FK
        uuid user_id FK
        varchar title
        jsonb system_prompt
        int message_count
        timestamp created_at
        timestamp updated_at
    }
    MESSAGE {
        uuid id PK
        uuid conversation_id FK
        varchar role
        text content
        jsonb sources
        int token_count
        timestamp created_at
    }
```

## 2. 表结构字典

| 表 | 说明 | 关键索引 |
|---|---|---|
| user | 系统用户 | username(UK), email(UK), role, is_active |
| knowledge_base | 知识库 | owner_id, status, name(gin_trgm), is_deleted |
| kb_member | 知识库成员(M2M+角色) | (kb_id,user_id) UK, user_id |
| document | 文档 | kb_id, status, minio_key, uploaded_by |
| chunk | 文档分块(元数据,向量在ES) | document_id, kb_id, chunk_index |
| process_task | 异步任务记录 | document_id, status, celery_task_id |
| conversation | 问答会话 | kb_id, user_id, created_at DESC |
| message | 会话消息 | conversation_id, created_at, role |

## 3. DDL 脚本

见 `infra/init_db.sql`（与后端 Alembic 初始迁移一致）。

### 3.1 变更历史

| 日期 | 变更 | 迁移 SQL |
|------|------|---------|
| 2026-09-21 | document.file_type 枚举扩展（+pptx/xlsx/jpg/png/bmp/webp/tiff）；新增 document.meta JSONB | `ALTER TABLE document DROP CONSTRAINT ck_doc_filetype; ALTER TABLE document ADD CONSTRAINT ck_doc_filetype CHECK (file_type IN ('pdf','docx','pptx','xlsx','txt','md','html','jpg','png','bmp','webp','tiff')); ALTER TABLE document ADD COLUMN meta JSONB DEFAULT '{}'::jsonb;` |

## 4. Elasticsearch 索引

```
Index: kb_chunks
mappings:
  chunk_id      keyword
  document_id   keyword
  kb_id         keyword
  chunk_index   integer
  content       text (analyzer: ik_max_word)
  embedding     dense_vector (dims=3584, similarity=cosine)
  token_count   integer
  metadata      object (dynamic)
  file_name     keyword
  file_type     keyword
  created_at    date
settings:
  number_of_shards: 1
  number_of_replicas: 0
  analysis.analyzer.ik_max_word (type: custom, tokenizer: ik_max_word)
```

> 需安装 ES 插件 `elasticsearch-analysis-ik`。
