SET NAMES utf8mb4;
-- 本文件由服务目录的 sql 脚本复制生成，供 MySQL 容器首次初始化时自动建表。
-- 修改请以 services/<服务名>/sql/*.sql 为准，并同步本文件。

-- 来源: services/capability-service/sql/01_init.sql
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

-- 来源: services/capability-service/sql/02_seed.sql
-- capability-service 演示数据：可重复导入，导入后回到已知状态。
-- 对应开发指南 13.2 与接口契约第 7 节：2 个分类 + 3 个能力（其中 1 个对话能力 online）。
-- chat-completions / long-summary 的 param_schema 与 ai-chat-service 执行器约束一致：
-- 内联 Draft 2020-12、对象根类型、无 $ref/$id；已有业务库请改用 03 增量迁移。
-- 仅供本地演示与联调，不含任何真实密钥。
USE capability_db;

INSERT INTO t_capability_category (id, name, code, sort, status)
VALUES
  (1, '语言处理', 'nlp', 10, 'enabled'),
  (2, '多模态', 'multimodal', 20, 'enabled')
AS new
ON DUPLICATE KEY UPDATE
  name = new.name,
  sort = new.sort,
  status = new.status,
  is_deleted = 0;

INSERT INTO t_capability
  (id, category_id, name, code, service_name, path, param_schema, price_per_call, status, description)
VALUES
  (
    1, 1, '多轮对话', 'chat-completions', 'ai-chat-service', '/api/chat/completions',
    JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT(
        'messages', JSON_OBJECT(
          'type', 'array',
          'minItems', 1,
          'maxItems', 40,
          'items', JSON_OBJECT(
            'type', 'object',
            'properties', JSON_OBJECT(
              'role', JSON_OBJECT(
                'type', 'string',
                'enum', JSON_ARRAY('system', 'user', 'assistant')
              ),
              'content', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000)
            ),
            'required', JSON_ARRAY('role', 'content'),
            'additionalProperties', CAST('false' AS JSON)
          )
        ),
        'temperature', JSON_OBJECT('type', 'number', 'minimum', 0, 'maximum', 2)
      ),
      'required', JSON_ARRAY('messages'),
      'additionalProperties', CAST('false' AS JSON)
    ),
    5, 'online', '多轮对话与文本生成，支持 Mock 与真实模型；主闭环演示能力'
  ),
  (
    2, 1, '长文本摘要', 'long-summary', 'ai-chat-service', '/api/chat/completions',
    JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT(
        'text', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000),
        'max_length', JSON_OBJECT(
          'type', 'integer', 'minimum', 30, 'maximum', 1000, 'default', 200
        )
      ),
      'required', JSON_ARRAY('text'),
      'additionalProperties', CAST('false' AS JSON)
    ),
    3, 'online', '把长文档压缩成可执行的结论与行动项'
  ),
  (
    3, 2, '视觉理解', 'vision-parse', 'ai-chat-service', '/api/chat/completions',
    JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT('image_url', JSON_OBJECT('type', 'string')),
      'required', JSON_ARRAY('image_url')
    ),
    8, 'draft', '从图片中识别对象与结构；保持 draft 用于验证市场接口不会返回未上架能力'
  )
AS new
ON DUPLICATE KEY UPDATE
  category_id = new.category_id,
  name = new.name,
  service_name = new.service_name,
  path = new.path,
  param_schema = new.param_schema,
  price_per_call = new.price_per_call,
  status = new.status,
  description = new.description,
  is_deleted = 0;

-- 来源: services/capability-service/sql/03_align_executor_schema.sql
-- capability-service 增量迁移：把已登记执行器的 param_schema 对齐到
-- ai-chat-service 的受控输入约束（内联 Draft 2020-12，无任何 $ref/$id）。
--
-- 只更新可明确识别的旧版默认 Schema：
-- 1. 完整 JSON 结构等于旧 seed 的 chat-completions / long-summary Schema；
-- 2. online 执行器的 param_schema 为空。
-- 不用“缺少某个字段”推断 Schema 是旧版本，避免覆盖业务自定义约束；
-- draft/offline 的空 Schema 保持为空。价格、状态和其他字段均不改写。
-- 重复执行安全；执行前仍建议备份下文筛选出的行。
--
-- 恢复方式：执行前先备份受影响列，例如
--   CREATE TABLE t_capability_schema_backup_<日期> AS
--   SELECT id, code, param_schema FROM t_capability WHERE code IN ('chat-completions','long-summary');
-- 如需回滚，按备份中的 id 写回 param_schema。
USE capability_db;

-- chat-completions：messages 1–40 条，role 三选一，content 1–12000，
-- 可选 temperature 0–2；最后一条必须是 user 由执行器校验。
UPDATE t_capability
SET param_schema = JSON_OBJECT(
  'type', 'object',
  'properties', JSON_OBJECT(
    'messages', JSON_OBJECT(
      'type', 'array',
      'minItems', 1,
      'maxItems', 40,
      'items', JSON_OBJECT(
        'type', 'object',
        'properties', JSON_OBJECT(
          'role', JSON_OBJECT(
            'type', 'string',
            'enum', JSON_ARRAY('system', 'user', 'assistant')
          ),
          'content', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000)
        ),
        'required', JSON_ARRAY('role', 'content'),
        'additionalProperties', CAST('false' AS JSON)
      )
    ),
    'temperature', JSON_OBJECT('type', 'number', 'minimum', 0, 'maximum', 2)
  ),
  'required', JSON_ARRAY('messages'),
  'additionalProperties', CAST('false' AS JSON)
)
WHERE code = 'chat-completions'
  AND is_deleted = 0
  AND (
    (param_schema IS NULL AND status = 'online')
    OR param_schema = JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT('messages', JSON_OBJECT('type', 'array')),
      'required', JSON_ARRAY('messages')
    )
  );

-- long-summary：text 1–12000（非空白仍由执行器校验），
-- max_length 可选整数 30–1000，默认 200。
UPDATE t_capability
SET param_schema = JSON_OBJECT(
  'type', 'object',
  'properties', JSON_OBJECT(
    'text', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000),
    'max_length', JSON_OBJECT(
      'type', 'integer', 'minimum', 30, 'maximum', 1000, 'default', 200
    )
  ),
  'required', JSON_ARRAY('text'),
  'additionalProperties', CAST('false' AS JSON)
)
WHERE code = 'long-summary'
  AND is_deleted = 0
  AND (
    (param_schema IS NULL AND status = 'online')
    OR param_schema = JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT('text', JSON_OBJECT('type', 'string')),
      'required', JSON_ARRAY('text')
    )
  );
