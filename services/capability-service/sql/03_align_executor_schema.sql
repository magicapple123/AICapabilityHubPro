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
