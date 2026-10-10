-- ============================================================
-- kb-management — 2026-10-10 PageIndex 检索选项迁移
-- 1) process_task.task_type 约束扩展：+ 'pageindex'（树索引构建任务）
-- 幂等：可重复执行（约束先 DROP IF EXISTS）
-- ============================================================

BEGIN;

ALTER TABLE process_task DROP CONSTRAINT IF EXISTS process_task_task_type_check;
ALTER TABLE process_task DROP CONSTRAINT IF EXISTS ck_task_type;
ALTER TABLE process_task ADD CONSTRAINT process_task_task_type_check
    CHECK (task_type IN ('parse', 'chunk_index', 'pageindex', 'cleanup'));

COMMIT;

-- 验证
-- SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--   WHERE conrelid = 'process_task'::regclass AND contype = 'c';
