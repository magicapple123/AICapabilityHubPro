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
                'enum', JSON_ARRAY('system', 'user', 'assistant', 'tool')
              ),
              'content', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000),
              'tool_call_id', JSON_OBJECT('type', 'string', 'maxLength', 64),
              'name', JSON_OBJECT('type', 'string', 'maxLength', 64),
              'tool_calls', JSON_OBJECT(
                'type', 'array',
                'maxItems', 64,
                'items', JSON_OBJECT('type', 'object')
              )
            ),
            'required', JSON_ARRAY('role'),
            'additionalProperties', CAST('false' AS JSON)
          )
        ),
        'temperature', JSON_OBJECT('type', 'number', 'minimum', 0, 'maximum', 2),
        'tools', JSON_OBJECT(
          'type', 'array',
          'maxItems', 64,
          'items', JSON_OBJECT('type', 'object')
        ),
        'tool_choice', JSON_OBJECT('type', JSON_ARRAY('string', 'object')),
        'parallel_tool_calls', JSON_OBJECT('type', 'boolean')
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


-- 来源: services/capability-service/sql/04_add_billing_mode.sql
-- capability-service 增量迁移（C2 双轨计费）。
--
-- 只增列、不改价格：旧的两个能力（chat-completions / long-summary）
-- 自动落到 billing_mode='per_call'，price_per_call 原值不动，
-- 因此按次计费的金额与响应字段完全不变（红线 3）。
-- 重复执行安全：列已存在时跳过 ALTER（MySQL 不支持 ADD COLUMN IF NOT EXISTS）。
-- 执行前请在备份上先跑一遍并确认可重复执行（红线 4）。
USE capability_db;

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

CALL add_column_if_missing('t_capability', 'billing_mode',
  "VARCHAR(16) NOT NULL DEFAULT 'per_call' COMMENT '计价模式 per_call按次/per_token按token/per_unit按件' AFTER price_per_call");
CALL add_column_if_missing('t_capability', 'price_per_1k_input',
  "INT NOT NULL DEFAULT 0 COMMENT '每 1000 输入 token 的积分单价' AFTER billing_mode");
CALL add_column_if_missing('t_capability', 'price_per_1k_output',
  "INT NOT NULL DEFAULT 0 COMMENT '每 1000 输出 token 的积分单价' AFTER price_per_1k_input");
CALL add_column_if_missing('t_capability', 'price_per_unit',
  "INT NOT NULL DEFAULT 0 COMMENT '按件计费的单件积分单价' AFTER price_per_1k_output");
CALL add_column_if_missing('t_capability', 'unit',
  "VARCHAR(16) NOT NULL DEFAULT '' COMMENT '按件计价单位，如 张' AFTER price_per_unit");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- 迁移后自检：旧能力必须仍是 per_call 且单价非 0（应为 5 / 3）。
SELECT id, code, billing_mode, price_per_call, price_per_1k_input, price_per_1k_output
FROM t_capability
WHERE code IN ('chat-completions', 'long-summary') AND is_deleted = 0;


-- 来源: services/capability-service/sql/05_add_operation_log.sql
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


-- 来源: services/capability-service/sql/06_add_executor.sql
-- capability-service 增量迁移（D2 执行器抽象 / D4 输出上限）。
--
-- 只增列并按 code 回填历史执行器，不动价格、状态与 Schema。
-- 重复执行安全。
USE capability_db;

DROP PROCEDURE IF EXISTS add_column_if_missing;
DELIMITER $$
CREATE PROCEDURE add_column_if_missing(
  IN p_table VARCHAR(64), IN p_column VARCHAR(64), IN p_definition TEXT
)
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = p_column
  ) THEN
    SET @ddl := CONCAT('ALTER TABLE `', p_table, '` ADD COLUMN `', p_column, '` ', p_definition);
    PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
  END IF;
END$$
DELIMITER ;

CALL add_column_if_missing('t_capability', 'executor',
  "VARCHAR(32) NOT NULL DEFAULT '' COMMENT '执行器 chat/summary/image-generate/embedding' AFTER unit");
CALL add_column_if_missing('t_capability', 'provider_alias',
  "VARCHAR(64) NOT NULL DEFAULT '' COMMENT '供应商别名，跨库不建外键' AFTER executor");
CALL add_column_if_missing('t_capability', 'max_output_tokens',
  "INT NOT NULL DEFAULT 1024 COMMENT '单次输出 token 上限，请求取 min(请求值, 本值)' AFTER provider_alias");

DROP PROCEDURE IF EXISTS add_column_if_missing;

-- 历史能力回填执行器：只按已知 code 映射，不猜测其它编码。
-- 同一 code 已是目标值时不会重复写（幂等）。
UPDATE t_capability SET executor = 'chat'
WHERE code = 'chat-completions' AND is_deleted = 0 AND executor = '';
UPDATE t_capability SET executor = 'summary'
WHERE code = 'long-summary' AND is_deleted = 0 AND executor = '';

-- 迁移自检：旧两行必须已带执行器，且价格未变。
SELECT id, code, executor, provider_alias, max_output_tokens, price_per_call
FROM t_capability WHERE code IN ('chat-completions', 'long-summary') AND is_deleted = 0;


-- 来源: services/capability-service/sql/07_add_exposed_to_market.sql
-- capability-service 增量迁移（E4 模型服务视图：市场展示开关）。
--
-- 默认 1：历史能力继续在市场可见，行为不变。
-- 与 status 独立：status=online 决定"能不能调"，exposed_to_market 决定"愿不愿被看见"。
-- 重复执行安全。
USE capability_db;

SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'capability_db'
    AND TABLE_NAME = 't_capability'
    AND COLUMN_NAME = 'exposed_to_market'
);
SET @ddl := IF(
  @exists = 0,
  'ALTER TABLE t_capability ADD COLUMN exposed_to_market TINYINT NOT NULL DEFAULT 1 COMMENT ''是否在市场展示 0否1是'' AFTER max_output_tokens',
  'SELECT ''t_capability.exposed_to_market already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT id, code, status, exposed_to_market FROM t_capability WHERE is_deleted = 0 ORDER BY id;


-- 来源: services/capability-service/sql/08_add_active_code.sql
-- capability-service 增量迁移（D5 软删 code 复用）。
--
-- 问题（文档描述的原始 bug）
-- ==========================
-- 旧约束是 `UNIQUE KEY uk_capability_code (code, is_deleted)`，语义是
-- "同一 code 最多 1 条未删除 + 最多 1 条已删除"。于是：
--   建 code=x → 删 code=x（1 条已删除，占满 is_deleted=1 位）
--   → 再建 code=x → 再删 code=x → 撞 uk_capability_code（1062）。
-- 也就是"同一个编码只能被软删一次"，运营反复上下架同名能力就会失败。
--
-- 修法
-- ====
-- 用一个**生成列**把"只有当行未删除时才存在"的编码物化出来：
--   active_code = IF(is_deleted = 0, code, NULL)
-- NULL 在 MySQL 唯一索引里不参与去重（多行 NULL 允许共存），所以：
--   * 未删除行：同一 code 仍最多 1 条 —— 原来的业务约束不变；
--   * 已删除行：active_code 一律为 NULL —— 想软删多少次都行。
--
-- 索引取舍
-- ========
-- 旧 `uk_capability_code (code, is_deleted)` **改名为非唯一** `idx_capability_code (code, is_deleted)`，
-- 而不是直接删除。原因：仓储层的 `exists_code()` 与编辑查重走的是
-- `WHERE code = ? AND is_deleted = 0`，唯一性不再由它保证，但这个索引仍然是
-- 该查询的最优访问路径；直接删掉会让查重退化成全表扫描。
-- 唯一性改由 `uk_capability_active_code (active_code)` 承担。
--
-- 选 STORED 而不是 VIRTUAL：索引在两种形态下都可建，但 STORED 让
-- `SHOW CREATE TABLE` / 运维排查时能直接 `SELECT active_code` 看到判定结果，
-- 且不依赖每次读取时计算；本表是目录表（写少读多、行数很小），代价可忽略。
--
-- 重复执行安全。

USE capability_db;

-- ---------------------------------------------------------------- 1. 生成列

DROP PROCEDURE IF EXISTS add_active_code_column;
DELIMITER $$
CREATE PROCEDURE add_active_code_column()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 't_capability'
      AND COLUMN_NAME = 'active_code'
  ) THEN
    ALTER TABLE t_capability
      ADD COLUMN active_code VARCHAR(64)
        GENERATED ALWAYS AS (IF(is_deleted = 0, code, NULL)) STORED
        COMMENT '生成列：未删除时等于 code，已删除时为 NULL，用于唯一约束（D5）';
  END IF;
END$$
DELIMITER ;

CALL add_active_code_column();
DROP PROCEDURE IF EXISTS add_active_code_column;

-- ---------------------------------------------------------------- 2. 新唯一索引

DROP PROCEDURE IF EXISTS add_active_code_unique;
DELIMITER $$
CREATE PROCEDURE add_active_code_unique()
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 't_capability'
      AND INDEX_NAME = 'uk_capability_active_code'
  ) THEN
    ALTER TABLE t_capability
      ADD UNIQUE KEY uk_capability_active_code (active_code);
  END IF;
END$$
DELIMITER ;

CALL add_active_code_unique();
DROP PROCEDURE IF EXISTS add_active_code_unique;

-- ------------------------------------------------- 3. 旧唯一索引降级为非唯一

DROP PROCEDURE IF EXISTS relax_legacy_code_unique;
DELIMITER $$
CREATE PROCEDURE relax_legacy_code_unique()
BEGIN
  -- 旧唯一索引存在时先删（不删的话它仍然拦着第二次软删）。
  IF EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 't_capability'
      AND INDEX_NAME = 'uk_capability_code'
      AND NON_UNIQUE = 0
  ) THEN
    ALTER TABLE t_capability DROP INDEX uk_capability_code;
  END IF;

  -- 补回非唯一索引，保住 exists_code() 的访问路径。
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 't_capability'
      AND INDEX_NAME = 'idx_capability_code'
  ) THEN
    ALTER TABLE t_capability ADD KEY idx_capability_code (code, is_deleted);
  END IF;
END$$
DELIMITER ;

CALL relax_legacy_code_unique();
DROP PROCEDURE IF EXISTS relax_legacy_code_unique;

-- 迁移自检：生成列必须与 is_deleted 一致，且未删除范围内 code 不再重复。
SELECT id, code, is_deleted, active_code FROM t_capability ORDER BY id;
SELECT code, COUNT(*) AS active_rows
FROM t_capability WHERE is_deleted = 0 GROUP BY code HAVING COUNT(*) > 1;


-- 来源: services/capability-service/sql/09_allow_tools_in_chat_schema.sql
-- capability-service 增量迁移（E2 工具调用：让 chat 能力的 Schema 接受 tools）。
--
-- 问题
-- ====
-- 旧 Schema 是"纯聊天"约束：messages.role 只允许 system/user/assistant，
-- 且对象 `additionalProperties: false`，任何工具相关字段（tools / tool_choice /
-- parallel_tool_calls / role=tool / tool_call_id / name）都会被判 2001。
-- 结果：E2 在代码层支持了工具透传，但演示能力本身调不通 —— 实测
-- `POST /api/chat/completions` 带 tools 直接返回 2001。
--
-- 修法
-- ====
-- 只放宽 chat-completions 这一条能力的 Schema（summary 等能力保持原样）：
--   1. role 枚举增加 `tool`；
--   2. 消息对象允许 `tool_call_id` / `name`（工具回灌用，仍禁止其他未知字段）；
--   3. 顶层允许 `tools` / `tool_choice` / `parallel_tool_calls`。
-- 三个字段都是**可选**的，不传时的行为与旧版完全一致。
--
-- 重复执行安全：整段是幂等 UPDATE，不依赖当前值。

USE capability_db;

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
            'enum', JSON_ARRAY('system', 'user', 'assistant', 'tool')
          ),
          'content', JSON_OBJECT('type', 'string', 'minLength', 1, 'maxLength', 12000),
          'tool_call_id', JSON_OBJECT('type', 'string', 'maxLength', 64),
          'name', JSON_OBJECT('type', 'string', 'maxLength', 64),
          'tool_calls', JSON_OBJECT(
            'type', 'array',
            'maxItems', 64,
            'items', JSON_OBJECT('type', 'object')
          )
        ),
        'required', JSON_ARRAY('role'),
        'additionalProperties', CAST('false' AS JSON)
      )
    ),
    'temperature', JSON_OBJECT('type', 'number', 'minimum', 0, 'maximum', 2),
    'tools', JSON_OBJECT(
      'type', 'array',
      'maxItems', 64,
      'items', JSON_OBJECT('type', 'object')
    ),
    'tool_choice', JSON_OBJECT('type', JSON_ARRAY('string', 'object')),
    'parallel_tool_calls', JSON_OBJECT('type', 'boolean')
  ),
  'required', JSON_ARRAY('messages'),
  'additionalProperties', CAST('false' AS JSON)
)
WHERE code = 'chat-completions' AND is_deleted = 0;

-- 自检：三条约束都在，tools 为可选属性。
SELECT id, code,
       JSON_EXTRACT(param_schema, '$.properties.tools') IS NOT NULL AS has_tools,
       JSON_SEARCH(param_schema, 'one', 'tool') IS NOT NULL AS role_allows_tool
FROM t_capability
WHERE code = 'chat-completions' AND is_deleted = 0;


-- 来源: services/capability-service/sql/10_add_openai_alias.sql
-- P2: public OpenAI-compatible model alias. Safe on existing and fresh databases.
SET @has_openai_alias = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
    AND COLUMN_NAME = 'openai_alias'
);
SET @ddl = IF(
  @has_openai_alias = 0,
  'ALTER TABLE t_capability ADD COLUMN openai_alias VARCHAR(64) NULL COMMENT ''OpenAI 兼容层公开模型名，在线 chat 能力唯一'' AFTER code',
  'SELECT ''t_capability.openai_alias already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @has_openai_alias_index = (
  SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
    AND INDEX_NAME = 'uk_capability_openai_alias'
);
SET @ddl = IF(
  @has_openai_alias_index = 0,
  'ALTER TABLE t_capability ADD UNIQUE KEY uk_capability_openai_alias (openai_alias)',
  'SELECT ''uk_capability_openai_alias already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_capability'
  AND COLUMN_NAME = 'openai_alias';
