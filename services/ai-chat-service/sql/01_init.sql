SET NAMES utf8mb4;
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
  content TEXT NOT NULL COMMENT '消息内容',
  call_status VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT '调用状态 success/degraded/failed',
  token_count INT NOT NULL DEFAULT 0 COMMENT 'token 数（估算或模型返回）',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  KEY idx_chat_message_session_deleted_id (session_id, is_deleted, id),
  KEY idx_chat_message_user_session (user_id, session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='对话消息';
