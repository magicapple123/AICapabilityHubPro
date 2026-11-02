SET NAMES utf8mb4;
-- capability-service 增量迁移（E4 模型服务视图：市场展示开关）。
--
-- 默认 1：历史能力继续在市场可见，行为不变。
-- 与 status 独立：status=online 决定"能不能调"，exposed_to_market 决定"愿不愿被看见"。
-- 重复执行安全。
USE capability_db;

SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'capability_db'
    AND TABLE_NAME = 't_capability'
    AND COLUMN_NAME = 'exposed_to_market'
);
SET @ddl := IF(
  @exists = 0,
  'ALTER TABLE t_capability ADD COLUMN exposed_to_market TINYINT NOT NULL DEFAULT 1 COMMENT ''是否在市场展示 0否1是'' AFTER max_output_tokens',
  'SELECT ''t_capability.exposed_to_market already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT id, code, status, exposed_to_market FROM t_capability WHERE is_deleted = 0 ORDER BY id;
