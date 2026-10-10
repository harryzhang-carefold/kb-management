-- ============================================================
-- kb-management — 2026-09-21 文档解析升级（MinerU）迁移脚本
-- 1) document.file_type 枚举扩展：+ pptx/xlsx/jpg/png/bmp/webp/tiff
-- 2) document 新增 meta JSONB 字段（解析元数据）
-- 幂等：可重复执行（约束先 DROP IF EXISTS）
-- ============================================================

BEGIN;

-- 1. file_type 约束扩展
ALTER TABLE document DROP CONSTRAINT IF EXISTS ck_doc_filetype;
ALTER TABLE document ADD CONSTRAINT ck_doc_filetype
    CHECK (file_type IN ('pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'html',
                         'jpg', 'png', 'bmp', 'webp', 'tiff'));

-- 2. meta 字段
ALTER TABLE document ADD COLUMN IF NOT EXISTS meta JSONB DEFAULT '{}'::jsonb;

COMMIT;

-- 验证
-- SELECT conname FROM pg_constraint WHERE conname = 'ck_doc_filetype';
-- SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'document' AND column_name IN ('file_type', 'meta');
