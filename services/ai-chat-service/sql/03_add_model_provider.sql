SET NAMES utf8mb4;
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
