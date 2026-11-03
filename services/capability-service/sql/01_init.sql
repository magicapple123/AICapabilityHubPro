SET NAMES utf8mb4;
-- capability-service 建表脚本；在已存在的 capability_db 上重复执行安全。
CREATE DATABASE IF NOT EXISTS capability_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE capability_db;

-- 骨架阶段占位表：保留以与组长样板保持一致，确认无引用后可手动清理。
CREATE TABLE IF NOT EXISTS t_capability_example (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  note VARCHAR(255) NOT NULL DEFAULT '' COMMENT '示例备注',
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='能力目录服务骨架示例表';

-- 能力分类。
-- 唯一性按“未删除范围内唯一”设计：用 (列, is_deleted) 组合唯一索引实现。
-- 已知约束：同一 code/name 只能被软删除一次，第二次删除会与旧记录冲突；
-- 如需无限次复用编码，需改用函数索引，暂列为本期不处理项。
CREATE TABLE IF NOT EXISTS t_capability_category (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  name VARCHAR(64) NOT NULL COMMENT '分类名称',
  code VARCHAR(64) NOT NULL COMMENT '分类编码，小写字母/数字/连字符',
  sort INT NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
  status VARCHAR(16) NOT NULL DEFAULT 'enabled' COMMENT '分类状态 enabled启用 disabled停用',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_capability_category_name (name, is_deleted),
  UNIQUE KEY uk_capability_category_code (code, is_deleted),
  KEY idx_capability_category_status_sort (status, is_deleted, sort)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='能力分类';

-- 能力目录条目。
-- status 取 draft 草稿 / online 上架 / offline 下架，只有 online 会在市场接口可见。
-- 与 t_capability_category 一致，code 在未删除范围内唯一。
CREATE TABLE IF NOT EXISTS t_capability (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  category_id BIGINT NOT NULL COMMENT '所属分类 ID',
  name VARCHAR(64) NOT NULL COMMENT '能力名称',
  code VARCHAR(64) NOT NULL COMMENT '能力编码，小写字母/数字/连字符',
  openai_alias VARCHAR(64) NULL COMMENT 'OpenAI 兼容层公开模型名，在线 chat 能力唯一',
  service_name VARCHAR(64) NOT NULL COMMENT '承载该能力的服务名',
  path VARCHAR(255) NOT NULL COMMENT '调用路径',
  param_schema JSON NULL COMMENT '参数 Schema（JSON 对象）',
  price_per_call INT NOT NULL DEFAULT 0 COMMENT '每次调用积分单价，整型',
  billing_mode VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call按次/per_token按token/per_unit按件',
  price_per_1k_input INT NOT NULL DEFAULT 0 COMMENT '每 1000 输入 token 的积分单价',
  price_per_1k_output INT NOT NULL DEFAULT 0 COMMENT '每 1000 输出 token 的积分单价',
  price_per_unit INT NOT NULL DEFAULT 0 COMMENT '按件计费的单件积分单价',
  unit VARCHAR(16) NOT NULL DEFAULT '' COMMENT '按件计价单位，如 张',
  status VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT '能力状态 draft草稿 online上架 offline下架',
  description VARCHAR(512) NOT NULL DEFAULT '' COMMENT '能力描述',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  -- D5：生成列。未删除时等于 code，已删除时为 NULL。
  -- NULL 不参与唯一去重，因此"同一 code 可以软删任意多次、再重建"，
  -- 而未删除范围内 code 仍然唯一。详见 08_add_active_code.sql。
  active_code VARCHAR(64)
    GENERATED ALWAYS AS (IF(is_deleted = 0, code, NULL)) STORED
    COMMENT '生成列：未删除时等于 code，已删除时为 NULL（D5）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_capability_openai_alias (openai_alias),
  UNIQUE KEY uk_capability_active_code (active_code),
  -- 唯一性已交给 active_code，这里只用于 exists_code() 的 `code = ? AND is_deleted = 0` 查重路径。
  KEY idx_capability_code (code, is_deleted),
  KEY idx_capability_category_status (category_id, is_deleted, status),
  KEY idx_capability_status_update (status, is_deleted, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='能力目录';

-- 运营操作审计（B1）。只追加：应用层没有 update / delete 接口，
-- repository 也没有对应方法；库层再用触发器拦住 UPDATE（见 05 增量脚本）。
CREATE TABLE IF NOT EXISTS t_operation_log (
  id BIGINT NOT NULL AUTO_INCREMENT COMMENT '主键',
  operator_id VARCHAR(64) NOT NULL COMMENT '操作人 user_id',
  operator_name VARCHAR(64) NOT NULL DEFAULT '' COMMENT '操作人名称快照',
  resource_type VARCHAR(32) NOT NULL COMMENT '资源类型 capability/category/user/points/apikey',
  resource_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '资源标识',
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
