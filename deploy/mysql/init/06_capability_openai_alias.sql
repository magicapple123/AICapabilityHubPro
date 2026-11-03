-- P2 incremental migration mirror. Kept beside init baselines for deployment parity.
USE capability_db;

SET @has_openai_alias = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
    AND COLUMN_NAME = 'openai_alias'
);
SET @ddl = IF(
  @has_openai_alias = 0,
  'ALTER TABLE t_capability ADD COLUMN openai_alias VARCHAR(64) NULL COMMENT ''OpenAI 兼容层公开模型名，在线 chat 能力唯一'' AFTER code',
  'SELECT ''t_capability.openai_alias already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_openai_alias_index = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
    AND INDEX_NAME = 'uk_capability_openai_alias'
);
SET @ddl = IF(
  @has_openai_alias_index = 0,
  'ALTER TABLE t_capability ADD UNIQUE KEY uk_capability_openai_alias (openai_alias)',
  'SELECT ''uk_capability_openai_alias already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
  AND COLUMN_NAME = 'openai_alias';
