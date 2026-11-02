SET NAMES utf8mb4;
-- ai-chat-service 增量迁移（A1 / C1）：
--   1. t_chat_message.error_code：失败占位消息的错误码，便于区分"没发过"与"调用失败"；
--   2. 修正 token_count 的列注释，语义固定为上游 usage 的 total（prompt+completion）。
--
-- 只增列、不改旧数据；旧行 error_code 为 NULL，token_count 保持原值不动。
-- 重复执行安全：列已存在时跳过 ALTER（MySQL 不支持 ADD COLUMN IF NOT EXISTS）。
-- 执行前请在备份上先跑一遍（红线 4）。
USE ai_chat_db;

SET @has_error_code := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'ai_chat_db'
    AND TABLE_NAME = 't_chat_message'
    AND COLUMN_NAME = 'error_code'
);
SET @ddl := IF(
  @has_error_code = 0,
  'ALTER TABLE t_chat_message ADD COLUMN error_code INT NULL COMMENT ''失败错误码，仅 failed 占位消息写入'' AFTER token_count',
  'SELECT ''t_chat_message.error_code already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

ALTER TABLE t_chat_message
  MODIFY COLUMN token_count INT NOT NULL DEFAULT 0
  COMMENT 'token 总数（上游 usage total；Mock 为估算，见响应 usage_source）';
