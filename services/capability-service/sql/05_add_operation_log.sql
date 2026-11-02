SET NAMES utf8mb4;
-- capability-service 增量迁移（B1 运营审计）。
--
-- 只建新表，不动任何既有表与数据；重复执行安全。
-- 应用层只追加：没有 update / delete 接口，repository 也不提供对应方法。
-- user-service 的同类表在批 5（F1）以同构字段建立，四库物理隔离、不跨库查询。
USE capability_db;

CREATE TABLE IF NOT EXISTS t_operation_log (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  operator_id VARCHAR(64) NOT NULL COMMENT '操作人 user_id（网关注入）',
  operator_name VARCHAR(64) NOT NULL DEFAULT '' COMMENT '操作人名称快照',
  resource_type VARCHAR(32) NOT NULL COMMENT '资源类型 capability/category/user/points/apikey',
  resource_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '资源标识，自增 ID 或业务编码',
  action VARCHAR(32) NOT NULL COMMENT '动作 create/update/status/delete/rollback',
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

-- 库层兜底：即使将来有人新增了写接口，也无法 UPDATE 审计行。
-- DELETE 保留给运维保留期清理（不是业务接口），因此不拦。
DROP TRIGGER IF EXISTS trg_operation_log_no_update;
DELIMITER $$
CREATE TRIGGER trg_operation_log_no_update
BEFORE UPDATE ON t_operation_log
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 't_operation_log is append-only: UPDATE is forbidden';
END$$
DELIMITER ;
