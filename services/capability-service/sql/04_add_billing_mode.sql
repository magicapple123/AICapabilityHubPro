SET NAMES utf8mb4;
-- capability-service 增量迁移（C2 双轨计费）。
--
-- 只增列、不改价格：旧的两个能力（chat-completions / long-summary）
-- 自动落到 billing_mode='per_call'，price_per_call 原值不动，
-- 因此按次计费的金额与响应字段完全不变（红线 3）。
-- 重复执行安全：列已存在时跳过 ALTER（MySQL 不支持 ADD COLUMN IF NOT EXISTS）。
-- 执行前请在备份上先跑一遍并确认可重复执行（红线 4）。
USE capability_db;

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

CALL add_column_if_missing('t_capability', 'billing_mode',
  "VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call按次/per_token按token/per_unit按件' AFTER price_per_call");
CALL add_column_if_missing('t_capability', 'price_per_1k_input',
  "INT NOT NULL DEFAULT 0 COMMENT '每 1000 输入 token 的积分单价' AFTER billing_mode");
CALL add_column_if_missing('t_capability', 'price_per_1k_output',
  "INT NOT NULL DEFAULT 0 COMMENT '每 1000 输出 token 的积分单价' AFTER price_per_1k_input");
CALL add_column_if_missing('t_capability', 'price_per_unit',
  "INT NOT NULL DEFAULT 0 COMMENT '按件计费的单件积分单价' AFTER price_per_1k_output");
CALL add_column_if_missing('t_capability', 'unit',
  "VARCHAR(16) NOT NULL DEFAULT '' COMMENT '按件计价单位，如 张' AFTER price_per_unit");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- 迁移后自检：旧能力必须仍是 per_call 且单价非 0（应为 5 / 3）。
SELECT id, code, billing_mode, price_per_call, price_per_1k_input, price_per_1k_output
FROM t_capability
WHERE code IN ('chat-completions', 'long-summary') AND is_deleted = 0;
