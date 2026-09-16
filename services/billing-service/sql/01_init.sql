-- billing-service 建表脚本；在已存在的 billing_db 上重复执行安全。
CREATE DATABASE IF NOT EXISTS billing_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE billing_db;

-- 骨架阶段占位表：保留以与组长样板保持一致，确认无引用后可手动清理。
CREATE TABLE IF NOT EXISTS t_billing_example (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  note VARCHAR(255) NOT NULL DEFAULT '' COMMENT '示例备注',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='计量服务骨架示例表';

-- 调用明细。
-- request_id 为幂等键，(request_id, is_deleted) 组合唯一索引保证同一 requestId
-- 只落一条记录：重复上报不会重复扣分，也不会重复累计用量。
-- capability_id 缺省 0：当前 ai-chat 按“服务 + 固定单价”上报，未携带能力 ID。
CREATE TABLE IF NOT EXISTS t_call_record (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  request_id VARCHAR(64) NOT NULL COMMENT '幂等键，全链路 requestId',
  user_id BIGINT NOT NULL COMMENT '调用用户 ID',
  capability_id BIGINT NOT NULL DEFAULT 0 COMMENT '能力 ID，0 表示未关联具体能力',
  service_name VARCHAR(64) NOT NULL DEFAULT '' COMMENT '承载调用的服务名',
  cost BIGINT NOT NULL DEFAULT 0 COMMENT '本次消耗积分（整数）',
  call_status VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT '调用状态 success成功 degraded降级 failed失败',
  duration_ms INT NOT NULL DEFAULT 0 COMMENT '调用耗时（毫秒）',
  model_name VARCHAR(128) NOT NULL DEFAULT '' COMMENT '模型名，Mock 模式为请求中的 model',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_call_record_request (request_id, is_deleted),
  KEY idx_call_record_user_time (user_id, is_deleted, create_time),
  KEY idx_call_record_service_time (service_name, is_deleted, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='调用明细';

-- 按天用量聚合。
-- (stat_date, user_id, capability_id) 联合唯一，写入使用
-- INSERT ... ON DUPLICATE KEY UPDATE 原子累加，避免并发丢失更新。
-- 本表只累加不软删除，因此 is_deleted 不进入唯一键。
CREATE TABLE IF NOT EXISTS t_usage_daily (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  stat_date DATE NOT NULL COMMENT '统计日期（Asia/Shanghai）',
  user_id BIGINT NOT NULL COMMENT '调用用户 ID',
  capability_id BIGINT NOT NULL DEFAULT 0 COMMENT '能力 ID，0 表示未关联具体能力',
  call_count BIGINT NOT NULL DEFAULT 0 COMMENT '当日调用次数',
  total_cost BIGINT NOT NULL DEFAULT 0 COMMENT '当日消耗积分合计',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_usage_daily (stat_date, user_id, capability_id),
  KEY idx_usage_daily_date (stat_date, is_deleted),
  KEY idx_usage_daily_user (user_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='按天用量聚合';
