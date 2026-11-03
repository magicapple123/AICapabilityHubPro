SET NAMES utf8mb4;
-- 本文件由服务目录的 sql 脚本复制生成，供 MySQL 容器首次初始化时自动建表。
-- 修改请以 services/<服务名>/sql/*.sql 为准，并同步本文件。

-- 来源: services/billing-service/sql/01_init.sql
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
  unit_price BIGINT NULL COMMENT '登记单价，历史未知为 NULL',
  cost BIGINT NOT NULL DEFAULT 0 COMMENT '本次消耗积分（整数）',
  billing_mode VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call/per_token/per_unit',
  prompt_tokens INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（上游 usage）',
  completion_tokens INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（上游 usage）',
  token_source VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT 'token 来源 upstream/mock/missing/unknown',
  units INT NOT NULL DEFAULT 1 COMMENT '按件计费的数量（张/次），其余模式为 1',
  call_status VARCHAR(16) NOT NULL DEFAULT 'success' COMMENT '调用状态 success成功 degraded降级 failed失败',
  duration_ms INT NOT NULL DEFAULT 0 COMMENT '调用耗时（毫秒）',
  model_name VARCHAR(128) NOT NULL DEFAULT '' COMMENT '模型名，Mock 模式为请求中的 model',
  images JSON NULL COMMENT '图片产物列表 [{url, revised_prompt}]，仅文生图有值（D3）',
  api_key_id BIGINT NULL COMMENT '调用使用的 API Key ID（P6），历史行为 NULL',
  entrypoint VARCHAR(16) NOT NULL DEFAULT '' COMMENT '入口 web/platform_api/openai_compat，历史行为空串（P6）',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_call_record_request (request_id, is_deleted),
  KEY idx_call_record_user_time (user_id, is_deleted, create_time),
  KEY idx_call_record_service_time (service_name, is_deleted, create_time),
  KEY idx_call_record_api_key_time (api_key_id, is_deleted, create_time)
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


-- 来源: services/billing-service/sql/02_seed.sql
-- billing-service 演示数据：可重复导入，导入后回到已知状态。
-- 对应开发指南 13.2：保证拉下来即可演示“查用量”页面。
--
-- 演示用户与 user-service 的 02_seed.sql 保持一致：
--   user_id=1 demo（余额 100）、user_id=2 demopoor（余额 0）。
-- 明细只写 2 条 Mock 调用，日期固定为 2026-09-15，便于稳定断言；
-- 不含任何真实密钥。
USE billing_db;

INSERT INTO t_call_record
  (id, request_id, user_id, capability_id, service_name, cost, call_status, duration_ms, model_name, create_time)
VALUES
  (1, 'seed-demo-0001', 1, 1, 'ai-chat-service', 5, 'success', 320, 'mock-model', '2026-09-15 10:00:00'),
  (2, 'seed-demo-0002', 1, 1, 'ai-chat-service', 5, 'success', 280, 'mock-model', '2026-09-15 10:05:00')
AS new
ON DUPLICATE KEY UPDATE
  user_id = new.user_id,
  capability_id = new.capability_id,
  service_name = new.service_name,
  cost = new.cost,
  call_status = new.call_status,
  duration_ms = new.duration_ms,
  model_name = new.model_name,
  -- 明细时间必须与 t_usage_daily.stat_date 对齐，否则演示数据的“按天”
  -- 与“明细”两个口径会互相矛盾。
  create_time = new.create_time,
  is_deleted = 0;

INSERT INTO t_usage_daily (id, stat_date, user_id, capability_id, call_count, total_cost)
VALUES
  (1, '2026-09-15', 1, 1, 2, 10)
AS new
ON DUPLICATE KEY UPDATE
  call_count = new.call_count,
  total_cost = new.total_cost,
  is_deleted = 0;


-- 来源: services/billing-service/sql/03_add_token_usage.sql
-- billing-service 增量迁移（C1 token 用量 / C2 双轨计费）。
--
-- 只增列，不改旧数据：旧行落到 0 / 0 / '' / 'per_call' / 1，
-- 历史"按次"账单的 cost 与 unit_price 完全不变。
-- 重复执行安全：列已存在时跳过 ALTER（MySQL 不支持 ADD COLUMN IF NOT EXISTS）。
-- 执行前请在备份上先跑一遍并确认可重复执行（红线 4）。
USE billing_db;

-- 通用增列过程：列不存在才执行 DDL。
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

CALL add_column_if_missing('t_call_record', 'billing_mode',
  "VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call/per_token/per_unit' AFTER cost");
CALL add_column_if_missing('t_call_record', 'prompt_tokens',
  "INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（上游 usage）' AFTER billing_mode");
CALL add_column_if_missing('t_call_record', 'completion_tokens',
  "INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（上游 usage）' AFTER prompt_tokens");
CALL add_column_if_missing('t_call_record', 'token_source',
  "VARCHAR(16) NOT NULL DEFAULT 'unknown' COMMENT 'token 来源 upstream/mock/missing/unknown' AFTER completion_tokens");
CALL add_column_if_missing('t_call_record', 'units',
  "INT NOT NULL DEFAULT 1 COMMENT '按件计费的数量（张/次），其余模式为 1' AFTER token_source");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- token_source 默认值从 '' 收紧为 'unknown'：'' 无法区分"历史未记录"与"上游没给"。
-- 只改默认值与注释，已有行（含 ''）保持不变。
ALTER TABLE t_call_record
  MODIFY COLUMN token_source VARCHAR(16) NOT NULL DEFAULT 'unknown'
  COMMENT 'token 来源 upstream/mock/missing/unknown';


-- 来源: services/billing-service/sql/04_add_images.sql
-- billing-service 增量迁移（D3 文生图：调用记录带图片产物）。
--
-- 为什么要在 billing 侧存：需求 D3 要求"调用记录可预览图片"，
-- 而 ai-chat 只把收据回给当次请求方，历史调用要在 billing 的明细里能看到图。
--
-- 只增列，不动任何既有列；旧记录该列为 NULL，语义是"没有图片产物"，
-- 与"有图片产物但列表为空"通过 JSON 类型区分（本服务写入时值为数组）。
-- 重复执行安全（MySQL 不支持 ADD COLUMN IF NOT EXISTS，用 information_schema 判断）。

USE billing_db;

SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'images'
);
SET @ddl := IF(
  @exists = 0,
  'ALTER TABLE t_call_record ADD COLUMN images JSON NULL COMMENT ''图片产物列表 [{url, revised_prompt}]，仅文生图有值'' AFTER model_name',
  'SELECT ''t_call_record.images already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 迁移自检：列已存在，且历史行全部为 NULL（不伪造数据）。
SELECT COUNT(*) AS total_rows,
       SUM(images IS NULL) AS rows_without_images
FROM t_call_record;


-- 来源: services/billing-service/sql/05_add_api_key_attribution.sql
-- billing-service 增量迁移（P6：调用记录的 API Key 归因与入口标记）。
--
-- 为什么要加这两列：Key 泄露时管理员只能"停号"，无法回答"这把 Key 调过什么"；
-- 网页调试台与接口调用在记录上也不可区分。两列都只加元数据，不存任何密钥材料。
--
-- 兼容性：
-- - `api_key_id` 可空，历史行保持 NULL（语义是"未知"），前端显示 "—" 且不参与按 Key 统计；
-- - `entrypoint` 默认空串，含义与 NULL 相同，避免把旧行伪造成 `web`。
-- 重复执行安全（MySQL 不支持 ADD COLUMN IF NOT EXISTS，用 information_schema 判断）。

USE billing_db;

SET @has_key := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'api_key_id'
);
SET @ddl := IF(
  @has_key = 0,
  'ALTER TABLE t_call_record ADD COLUMN api_key_id BIGINT NULL COMMENT ''调用使用的 API Key ID（P6），历史行为 NULL'' AFTER images',
  'SELECT ''t_call_record.api_key_id already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_entry := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'entrypoint'
);
SET @ddl := IF(
  @has_entry = 0,
  'ALTER TABLE t_call_record ADD COLUMN entrypoint VARCHAR(16) NOT NULL DEFAULT '''' COMMENT ''入口：web / platform_api / openai_compat，历史行为空串（P6）'' AFTER api_key_id',
  'SELECT ''t_call_record.entrypoint already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_index := (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND INDEX_NAME = 'idx_call_record_api_key_time'
);
SET @ddl := IF(
  @has_index = 0,
  'ALTER TABLE t_call_record ADD KEY idx_call_record_api_key_time (api_key_id, is_deleted, create_time)',
  'SELECT ''idx_call_record_api_key_time already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 迁移自检：两列已存在，且历史行的 Key 归因仍为空（不伪造数据）。
SELECT COUNT(*) AS total_rows,
       SUM(api_key_id IS NULL) AS rows_without_key,
       SUM(entrypoint = '') AS rows_without_entrypoint
FROM t_call_record;
