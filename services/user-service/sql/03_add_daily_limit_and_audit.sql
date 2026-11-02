SET NAMES utf8mb4;
-- user-service 增量迁移（C3 日积分预算 / F1 运营审计）。
--
-- 只增列 + 建新表，不动既有数据；重复执行安全。
USE user_db;

SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'user_db' AND TABLE_NAME = 't_user' AND COLUMN_NAME = 'daily_points_limit'
);
SET @ddl := IF(
  @exists = 0,
  'ALTER TABLE t_user ADD COLUMN daily_points_limit INT NOT NULL DEFAULT 0 COMMENT ''日积分上限，0 表示不限'' AFTER status',
  'SELECT ''t_user.daily_points_limit already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 与 capability_db.t_operation_log 同构：一库一张，四库隔离、不跨库查询。
CREATE TABLE IF NOT EXISTS t_operation_log (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  operator_id VARCHAR(64) NOT NULL COMMENT '操作人 user_id',
  operator_name VARCHAR(64) NOT NULL DEFAULT '' COMMENT '操作人名称快照',
  resource_type VARCHAR(32) NOT NULL COMMENT '资源类型 user/points/apikey',
  resource_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '资源标识',
  action VARCHAR(32) NOT NULL COMMENT '动作 status/adjust_points/update',
  before_json JSON NULL COMMENT '变更前快照（已脱敏）',
  after_json JSON NULL COMMENT '变更后快照（已脱敏）',
  request_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '全链路 requestId',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除，审计不使用',
  PRIMARY KEY (id),
  KEY idx_operation_log_resource (resource_type, resource_id, id),
  KEY idx_operation_log_operator (operator_id, id),
  KEY idx_operation_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='运营操作审计（只追加）';

DROP TRIGGER IF EXISTS trg_operation_log_no_update;
DELIMITER $$
CREATE TRIGGER trg_operation_log_no_update
BEFORE UPDATE ON t_operation_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 't_operation_log is append-only: UPDATE is forbidden';
END$$
DELIMITER ;

SELECT id, username, status, daily_points_limit FROM t_user WHERE is_deleted = 0 ORDER BY id LIMIT 10;
