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
  service_name VARCHAR(64) NOT NULL COMMENT '承载该能力的服务名',
  path VARCHAR(255) NOT NULL COMMENT '调用路径',
  param_schema JSON NULL COMMENT '参数 Schema（JSON 对象）',
  price_per_call INT NOT NULL DEFAULT 0 COMMENT '每次调用积分单价，整型',
  status VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT '能力状态 draft草稿 online上架 offline下架',
  description VARCHAR(512) NOT NULL DEFAULT '' COMMENT '能力描述',
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  is_deleted TINYINT NOT NULL DEFAULT 0 COMMENT '逻辑删除 0否1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_capability_code (code, is_deleted),
  KEY idx_capability_category_status (category_id, is_deleted, status),
  KEY idx_capability_status_update (status, is_deleted, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='能力目录';
