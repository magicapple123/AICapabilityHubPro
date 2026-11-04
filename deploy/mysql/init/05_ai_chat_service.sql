SET NAMES utf8mb4;
-- 本文件由服务目录的 sql 脚本复制生成，供 MySQL 容器首次初始化时自动建表。
-- 修改请以 services/<服务名>/sql/*.sql 为准，并同步本文件。

-- 来源: services/ai-chat-service/sql/01_init.sql
-- ai-chat-service 建表脚本；在已存在的 ai_chat_db 上重复执行安全。
CREATE DATABASE IF NOT EXISTS ai_chat_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE ai_chat_db;

-- 骨架阶段占位表：保留以与组长样板保持一致，确认无引用后可手动清理。
CREATE TABLE IF NOT EXISTS t_chat_example (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  note VARCHAR(255) NOT NULL DEFAULT '' COMMENT '示例备注',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话能力服务骨架示例表';

-- 对话会话。
-- last_message_time 供列表按活跃时间倒序，避免每次聚合消息表；
-- 索引 (user_id, is_deleted, last_message_time) 同时支撑列表查询与排序。
CREATE TABLE IF NOT EXISTS t_chat_session (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_id VARCHAR(64) NOT NULL COMMENT '用户标识（网关注入的 X-User-Id）',
  title VARCHAR(200) NOT NULL DEFAULT '新对话' COMMENT '会话标题，取自首条用户消息',
  last_message_time DATETIME NULL COMMENT '最后一条消息时间',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  KEY idx_chat_session_user_deleted_time (user_id, is_deleted, last_message_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话会话';

-- 会话消息。
-- call_status 记录该条助手消息的能力执行状态（success/degraded/failed）；
-- token_count 真实模型取 usage.total_tokens，Mock 与降级按字符数估算。
CREATE TABLE IF NOT EXISTS t_chat_message (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  session_id BIGINT NOT NULL COMMENT '会话 ID',
  user_id VARCHAR(64) NOT NULL COMMENT '用户标识',
  role VARCHAR(16) NOT NULL COMMENT '消息角色 system/user/assistant',
  content MEDIUMTEXT NOT NULL COMMENT '消息内容（单条上限 48000 字符，utf8mb4 约 144KB，TEXT 装不下）',
  call_status VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT '调用状态 success/degraded/failed',
  token_count INT NOT NULL DEFAULT 0 COMMENT 'token 总数（上游 usage total；Mock 为估算，见响应 usage_source）',
  error_code INT NULL COMMENT '失败错误码，仅 failed 占位消息写入',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  KEY idx_chat_message_session_deleted_id (session_id, is_deleted, id),
  KEY idx_chat_message_user_session (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话消息';


-- 来源: services/ai-chat-service/sql/02_add_message_error_code.sql
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


-- 来源: services/ai-chat-service/sql/03_add_model_provider.sql
-- ai-chat-service 增量迁移（D1 上游供应商）。
--
-- 供应商表放在 ai_chat_db：密钥不跨服务传，能力表只存 provider_alias 字符串。
-- 只建新表，不动既有数据；重复执行安全。
USE ai_chat_db;

CREATE TABLE IF NOT EXISTS t_model_provider (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  name VARCHAR(64) NOT NULL COMMENT '供应商名称',
  alias VARCHAR(64) NOT NULL COMMENT '别名，能力表 provider_alias 引用',
  protocol VARCHAR(32) NOT NULL COMMENT '协议 openai-chat/openai-image/openai-embedding/custom-http',
  base_url VARCHAR(512) NOT NULL COMMENT '基础地址，仅允许 https',
  api_key_cipher TEXT NOT NULL COMMENT 'AES-256-GCM 密文 v1:nonce:cipher',
  api_key_mask VARCHAR(32) NOT NULL DEFAULT '' COMMENT '密钥掩码，仅展示用',
  default_model VARCHAR(128) NOT NULL DEFAULT '' COMMENT '默认模型名',
  timeout_ms INT NOT NULL DEFAULT 30000 COMMENT '超时（毫秒）',
  extra_json JSON NULL COMMENT '协议扩展参数',
  status VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT 'draft草稿 enabled启用 disabled停用',
  last_test_ok_at DATETIME NULL COMMENT '最近一次连通性测试通过时间，启用前必须非空',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_model_provider_alias (alias, is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='上游模型供应商';


-- 来源: services/ai-chat-service/sql/04_widen_message_content.sql
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
