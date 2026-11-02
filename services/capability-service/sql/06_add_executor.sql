SET NAMES utf8mb4;
-- capability-service 增量迁移（D2 执行器抽象 / D4 输出上限）。
--
-- 只增列并按 code 回填历史执行器，不动价格、状态与 Schema。
-- 重复执行安全。
USE capability_db;

DROP PROCEDURE IF EXISTS add_column_if_missing;
DELIMITER $$
CREATE PROCEDURE add_column_if_missing(
  IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
  ) THEN
    SET @ddl := CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
    PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL add_column_if_missing('t_capability', 'executor',
  "VARCHAR(32) NOT NULL DEFAULT '' COMMENT '执行器 chat/summary/image-generate/embedding' AFTER unit");
CALL add_column_if_missing('t_capability', 'provider_alias',
  "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '供应商别名，跨库不建外键' AFTER executor");
CALL add_column_if_missing('t_capability', 'max_output_tokens',
  "INT NOT NULL DEFAULT 1024 COMMENT '单次输出 token 上限，请求取 min(请求值, 本值)' AFTER provider_alias");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- 历史能力回填执行器：只按已知 code 映射，不猜测其它编码。
-- 同一 code 已是目标值时不会重复写（幂等）。
UPDATE t_capability SET executor = 'chat'
WHERE code = 'chat-completions' AND is_deleted = 0 AND executor = '';
UPDATE t_capability SET executor = 'summary'
WHERE code = 'long-summary' AND is_deleted = 0 AND executor = '';

-- 迁移自检：旧两行必须已带执行器，且价格未变。
SELECT id, code, executor, provider_alias, max_output_tokens, price_per_call
FROM t_capability WHERE code IN ('chat-completions', 'long-summary') AND is_deleted = 0;
