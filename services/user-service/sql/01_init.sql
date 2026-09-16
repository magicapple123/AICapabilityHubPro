-- user-service 建表脚本；在已存在的 user_db 上重复执行安全。
CREATE DATABASE IF NOT EXISTS user_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE user_db;

-- 骨架阶段占位表：保留以与组长样板保持一致，确认无引用后可手动清理。
CREATE TABLE IF NOT EXISTS t_user_example (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  note VARCHAR(255) NOT NULL DEFAULT '' COMMENT '示例备注',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户服务骨架示例表';

-- 用户账号。
-- username 在未删除范围内唯一，用 (username, is_deleted) 组合唯一索引实现；
-- 已知约束同 capability-service：同一 username 只能被软删除一次。
CREATE TABLE IF NOT EXISTS t_user (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  username VARCHAR(32) NOT NULL COMMENT '登录名，3~32 位字母/数字/下划线/连字符',
  password_hash VARCHAR(255) NOT NULL COMMENT 'PBKDF2-HMAC-SHA256 自描述哈希串，禁止存明文',
  nickname VARCHAR(32) NOT NULL DEFAULT '' COMMENT '昵称',
  status VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT '用户状态 normal正常 disabled禁用',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_username (username, is_deleted),
  KEY idx_user_status (status, is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='用户账号';

-- 开发者 API Key。
-- secret_key 只在创建时返回一次，库内只保存 SHA-256 摘要（secret_hash）与展示用掩码；
-- access_key 可对外展示，在未删除范围内唯一。
CREATE TABLE IF NOT EXISTS t_api_key (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_id BIGINT NOT NULL COMMENT '所属用户 ID',
  name VARCHAR(32) NOT NULL DEFAULT '' COMMENT 'Key 备注名',
  access_key VARCHAR(64) NOT NULL COMMENT '对外标识 ak_ 开头',
  secret_hash VARCHAR(128) NOT NULL COMMENT 'secret_key 的 SHA-256 十六进制摘要',
  secret_mask VARCHAR(32) NOT NULL DEFAULT '' COMMENT '展示掩码，如 sk_****a1b2',
  status VARCHAR(16) NOT NULL DEFAULT 'enabled' COMMENT '状态 enabled启用 disabled禁用',
  expire_time DATETIME NULL COMMENT '过期时间，NULL 表示永不过期',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_api_key_access_key (access_key, is_deleted),
  KEY idx_api_key_user (user_id, status, is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='开发者 API Key';

-- 积分账户：一个用户一条，余额与冻结额均为整数（不使用浮点）。
-- balance 与 version 参与条件更新式扣分，避免并发超扣。
CREATE TABLE IF NOT EXISTS t_points_account (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_id BIGINT NOT NULL COMMENT '所属用户 ID',
  balance BIGINT NOT NULL DEFAULT 0 COMMENT '可用积分余额',
  frozen BIGINT NOT NULL DEFAULT 0 COMMENT '冻结积分',
  version INT NOT NULL DEFAULT 0 COMMENT '变更次数，便于排查与对账',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_points_account_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='积分账户';

-- 积分流水。
-- request_id 为幂等键：注册赠送用 register-{user_id}，调用扣分复用全链路 requestId；
-- (request_id, is_deleted) 组合唯一索引保证同一 requestId 只落一条流水，重复上报不二次扣分。
CREATE TABLE IF NOT EXISTS t_points_log (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  user_id BIGINT NOT NULL COMMENT '所属用户 ID',
  direction VARCHAR(8) NOT NULL COMMENT '方向 in收入 out支出',
  amount BIGINT NOT NULL DEFAULT 0 COMMENT '变动数量，正数',
  balance_after BIGINT NOT NULL DEFAULT 0 COMMENT '变动后余额快照',
  biz_type VARCHAR(32) NOT NULL DEFAULT '' COMMENT '业务类型 register注册赠送 call能力调用',
  request_id VARCHAR(64) NOT NULL COMMENT '幂等键，全链路 requestId',
  remark VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_points_log_request (request_id, is_deleted),
  KEY idx_points_log_user_time (user_id, is_deleted, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='积分流水';
