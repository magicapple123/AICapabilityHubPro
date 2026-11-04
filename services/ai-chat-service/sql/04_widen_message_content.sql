SET NAMES utf8mb4;
-- ai-chat-service 增量迁移：放宽 t_chat_message.content 的列宽（TEXT -> MEDIUMTEXT）。
--
-- 背景（实测复现的线上故障）：单条消息 content 的上限从 12000 提到 48000 后，
-- TEXT 的 65535 **字节**上限就成了新的瓶颈——中文在 utf8mb4 下约 3 字节/字，
-- 48000 字符约 144 KB，写库会被截断或在严格模式下直接报错 1406
-- （Data too long for column 'content'）。MEDIUMTEXT 上限 16 MB，余量充足。
--
-- 安全性：
--   * MODIFY COLUMN 只改类型，不重写语义：TEXT -> MEDIUMTEXT 是**放宽**，
--     已有数据全部原样保留（不存在截断风险），不 drop 表、不清库、不改 NULL 约束；
--   * 可重复执行：已经是 mediumtext 时走 SELECT 分支，不做任何 DDL。
--
-- 执行前备份（红线 4）：
--   CREATE TABLE t_chat_message_content_backup_<日期> AS
--   SELECT id, content FROM t_chat_message;
-- 回滚：列类型改回 TEXT 前必须先确认最长 content 的字节数 < 65535，否则会截断数据。

USE ai_chat_db;

SET @content_type := (
  SELECT DATA_TYPE FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 't_chat_message'
    AND COLUMN_NAME = 'content'
);

SELECT @content_type AS current_type_before_migration;

SET @ddl := IF(
  @content_type = 'mediumtext',
  'SELECT ''t_chat_message.content already MEDIUMTEXT'' AS skipped',
  'ALTER TABLE t_chat_message MODIFY COLUMN content MEDIUMTEXT NOT NULL COMMENT ''消息内容（单条上限 48000 字符，utf8mb4 约 144KB，TEXT 装不下）'''
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, CHARACTER_MAXIMUM_LENGTH
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME = 't_chat_message'
  AND COLUMN_NAME = 'content';
