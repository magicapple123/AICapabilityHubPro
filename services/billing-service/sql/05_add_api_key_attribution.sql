SET NAMES utf8mb4;
-- billing-service 增量迁移（P6：调用记录的 API Key 归因与入口标记）。
--
-- 为什么要加这两列：Key 泄露时管理员只能"停号"，无法回答"这把 Key 调过什么"；
-- 网页调试台与接口调用在记录上也不可区分。两列都只加元数据，不存任何密钥材料。
--
-- 兼容性：
-- - `api_key_id` 可空，历史行保持 NULL（语义是"未知"），前端显示 "—" 且不参与按 Key 统计；
-- - `entrypoint` 默认空串，含义与 NULL 相同，避免把旧行伪造成 `web`。
-- 重复执行安全（MySQL 不支持 ADD COLUMN IF NOT EXISTS，用 information_schema 判断）。

USE billing_db;

SET @has_key := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'api_key_id'
);
SET @ddl := IF(
  @has_key = 0,
  'ALTER TABLE t_call_record ADD COLUMN api_key_id BIGINT NULL COMMENT ''调用使用的 API Key ID（P6），历史行为 NULL'' AFTER images',
  'SELECT ''t_call_record.api_key_id already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_entry := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'entrypoint'
);
SET @ddl := IF(
  @has_entry = 0,
  'ALTER TABLE t_call_record ADD COLUMN entrypoint VARCHAR(16) NOT NULL DEFAULT '''' COMMENT ''入口：web / platform_api / openai_compat，历史行为空串（P6）'' AFTER api_key_id',
  'SELECT ''t_call_record.entrypoint already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_index := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND INDEX_NAME = 'idx_call_record_api_key_time'
);
SET @ddl := IF(
  @has_index = 0,
  'ALTER TABLE t_call_record ADD KEY idx_call_record_api_key_time (api_key_id, is_deleted, create_time)',
  'SELECT ''idx_call_record_api_key_time already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 迁移自检：两列已存在，且历史行的 Key 归因仍为空（不伪造数据）。
SELECT COUNT(*) AS total_rows,
       SUM(api_key_id IS NULL) AS rows_without_key,
       SUM(entrypoint = '') AS rows_without_entrypoint
FROM t_call_record;
