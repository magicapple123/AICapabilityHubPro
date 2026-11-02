SET NAMES utf8mb4;
-- billing-service 增量迁移（C1 token 用量 / C2 双轨计费）。
--
-- 只增列，不改旧数据：旧行落到 0 / 0 / '' / 'per_call' / 1，
-- 历史"按次"账单的 cost 与 unit_price 完全不变。
-- 重复执行安全：列已存在时跳过 ALTER（MySQL 不支持 ADD COLUMN IF NOT EXISTS）。
-- 执行前请在备份上先跑一遍并确认可重复执行（红线 4）。
USE billing_db;

-- 通用增列过程：列不存在才执行 DDL。
DROP PROCEDURE IF EXISTS add_column_if_missing;
DELIMITER $$
CREATE PROCEDURE add_column_if_missing(
  IN p_table VARCHAR(64),
  IN p_column VARCHAR(64),
  IN p_definition TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = p_table
      AND COLUMN_NAME = p_column
  ) THEN
    SET @ddl := CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
    PREPARE stmt FROM @ddl;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL add_column_if_missing('t_call_record', 'billing_mode',
  "VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call/per_token/per_unit' AFTER cost");
CALL add_column_if_missing('t_call_record', 'prompt_tokens',
  "INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（上游 usage）' AFTER billing_mode");
CALL add_column_if_missing('t_call_record', 'completion_tokens',
  "INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（上游 usage）' AFTER prompt_tokens");
CALL add_column_if_missing('t_call_record', 'token_source',
  "VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT 'token 来源 upstream/mock/missing/unknown' AFTER completion_tokens");
CALL add_column_if_missing('t_call_record', 'units',
  "INT NOT NULL DEFAULT 1 COMMENT '按件计费的数量（张/次），其余模式为 1' AFTER token_source");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- token_source 默认值从 '' 收紧为 'unknown'：'' 无法区分"历史未记录"与"上游没给"。
-- 只改默认值与注释，已有行（含 ''）保持不变。
ALTER TABLE t_call_record
  MODIFY COLUMN token_source VARCHAR(16) NOT NULL DEFAULT 'unknown'
  COMMENT 'token 来源 upstream/mock/missing/unknown';
