-- ============================================================
-- kb-management — PostgreSQL 初始化脚本
-- 由 docker-entrypoint-initdb.d 在首次启动时执行
-- 注意: 数据卷非空时不会再次执行（需重建数据卷）
-- 种子用户: admin / Admin@123 (bcrypt hash 见下)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ------------------------------------------------------------
-- app_user (表名避开 PG 内置 role "user")
-- ------------------------------------------------------------
CREATE TABLE app_user (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(50)  NOT NULL UNIQUE,
    email           VARCHAR(128) NOT NULL UNIQUE,
    password_hash   VARCHAR(256) NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'user'
                    CHECK (role IN ('admin', 'user')),
    display_name    VARCHAR(50)  DEFAULT '',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_user_role ON app_user(role);
CREATE INDEX idx_user_is_active ON app_user(is_active);

-- ------------------------------------------------------------
-- knowledge_base
-- ------------------------------------------------------------
CREATE TABLE knowledge_base (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id        UUID         NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    description     TEXT         DEFAULT '',
    status          VARCHAR(20)  NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived')),
    chunk_size      INT          NOT NULL DEFAULT 500,
    chunk_overlap   INT          NOT NULL DEFAULT 50,
    embedding_dim   INT          NOT NULL DEFAULT 3584,
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'gte-qwen2',
    settings        JSONB        DEFAULT '{}'::jsonb,
    is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_kb_owner ON knowledge_base(owner_id);
CREATE INDEX idx_kb_status ON knowledge_base(status) WHERE NOT is_deleted;
CREATE INDEX idx_kb_name_trgm ON knowledge_base USING GIN (name gin_trgm_ops);

-- ------------------------------------------------------------
-- kb_member
-- ------------------------------------------------------------
CREATE TABLE kb_member (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id       UUID NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL DEFAULT 'viewer'
                CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (kb_id, user_id)
);
CREATE INDEX idx_kb_member_user ON kb_member(user_id);

-- ------------------------------------------------------------
-- document
-- ------------------------------------------------------------
CREATE TABLE document (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id           UUID         NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    uploaded_by     UUID         NOT NULL REFERENCES app_user(id),
    filename        VARCHAR(255) NOT NULL,
    file_type       VARCHAR(50)  NOT NULL
                    CHECK (file_type IN ('pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'html',
                                         'jpg', 'png', 'bmp', 'webp', 'tiff')),
    file_size       BIGINT       NOT NULL DEFAULT 0,
    minio_key       VARCHAR(255) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'uploaded'
                    CHECK (status IN ('uploaded','parsing','parsed','chunking','embedding','indexed','failed')),
    chunk_count     INT          NOT NULL DEFAULT 0,
    full_text       TEXT         DEFAULT NULL,
    meta            JSONB        DEFAULT '{}'::jsonb,
    error_message   TEXT         DEFAULT NULL,
    version         INT          NOT NULL DEFAULT 1,
    is_deleted      BOOLEAN      NOT NULL DEFAULT FALSE,
    uploaded_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    indexed_at      TIMESTAMP    DEFAULT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_doc_kb ON document(kb_id) WHERE NOT is_deleted;
CREATE INDEX idx_doc_status ON document(status) WHERE NOT is_deleted;
CREATE INDEX idx_doc_minio ON document(minio_key);
CREATE INDEX idx_doc_uploaded_by ON document(uploaded_by);

-- ------------------------------------------------------------
-- chunk
-- ------------------------------------------------------------
CREATE TABLE chunk (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID         NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    kb_id           UUID         NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    chunk_index     INT          NOT NULL,
    content         TEXT         NOT NULL,
    token_count     INT          NOT NULL DEFAULT 0,
    metadata        JSONB        DEFAULT '{}'::jsonb,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_chunk_doc ON chunk(document_id);
CREATE INDEX idx_chunk_kb ON chunk(kb_id);

-- ------------------------------------------------------------
-- process_task
-- ------------------------------------------------------------
CREATE TABLE process_task (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID         NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    task_type       VARCHAR(50)  NOT NULL
                    CHECK (task_type IN ('parse', 'chunk_index', 'cleanup')),
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
    celery_task_id  VARCHAR(255) DEFAULT NULL,
    result          TEXT         DEFAULT NULL,
    error_message   TEXT         DEFAULT NULL,
    retry_count     INT          NOT NULL DEFAULT 0,
    started_at      TIMESTAMP    DEFAULT NULL,
    finished_at     TIMESTAMP    DEFAULT NULL,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_task_doc ON process_task(document_id);
CREATE INDEX idx_task_status ON process_task(status);

-- ------------------------------------------------------------
-- conversation
-- ------------------------------------------------------------
CREATE TABLE conversation (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kb_id           UUID         NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    user_id         UUID         NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    title           VARCHAR(200) DEFAULT '新对话',
    system_prompt   JSONB        DEFAULT NULL,
    message_count   INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_conv_kb ON conversation(kb_id);
CREATE INDEX idx_conv_user ON conversation(user_id);
CREATE INDEX idx_conv_created ON conversation(created_at DESC);

-- ------------------------------------------------------------
-- message
-- ------------------------------------------------------------
CREATE TABLE message (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id   UUID         NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
    role              VARCHAR(20)  NOT NULL CHECK (role IN ('user', 'assistant')),
    content           TEXT         NOT NULL,
    sources           JSONB        DEFAULT NULL,
    token_count       INT          NOT NULL DEFAULT 0,
    created_at        TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_msg_conv ON message(conversation_id);
CREATE INDEX idx_msg_created ON message(created_at);

-- ------------------------------------------------------------
-- updated_at 触发器
-- ------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_user_updated BEFORE UPDATE ON app_user
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_kb_updated BEFORE UPDATE ON knowledge_base
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_doc_updated BEFORE UPDATE ON document
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_conv_updated BEFORE UPDATE ON conversation
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 种子 admin (密码 Admin@123)
INSERT INTO app_user (username, email, password_hash, role, display_name)
VALUES ('admin', 'admin@kb.local',
        '$2b$12$6Ir3CPpLUzUb67U6oyuCnOxQaevsxsiQ4PSL0xgfwP2oWnZSCrLPK',
        'admin', '系统管理员');
