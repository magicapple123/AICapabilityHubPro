SET NAMES utf8mb4;
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
