SET NAMES utf8mb4;
-- capability-service 增量迁移：把**已有记录的目录 Schema** 的单条内容上限
-- 从 12000 提到 48000，与 ai-chat-service 的 `MAX_MESSAGE_CONTENT_LENGTH` 对齐。
--
-- 为什么必须有这一步：能力目录 Schema 是**运行时从本服务读取**再由执行器校验的，
-- 只改执行器的 Pydantic 常量，长消息仍会在这里被 `maxLength: 12000` 拒成 2001。
--   * chat-completions：`$.properties.messages.items.properties.content.maxLength`
--   * long-summary：   `$.properties.text.maxLength`
--
-- 幂等与安全：
--   * 只改路径上**当前值正好是 12000** 的记录：已经是 48000 的跳过，业务自定义的
--     其它上限（例如运营手写成 20000）也原样保留，不被静默覆盖；
--   * 只改这两个 JSON 叶子，价格、状态、provider/executor 绑定、其余 Schema 字段
--     一律不动；不 drop 表、不清库；
--   * 重复执行安全。
--
-- 执行前备份（脚本已内置打印；需要留档时再建物理备份）：
--   CREATE TABLE t_capability_schema_backup_<日期> AS
--   SELECT id, code, param_schema FROM t_capability
--   WHERE code IN ('chat-completions', 'long-summary');
-- 回滚：按备份中的 id 把 param_schema 写回即可。

USE capability_db;

-- 1) 备份：打印受影响行的旧值（回滚依据）。
SELECT id, code,
       JSON_EXTRACT(param_schema, '$.properties.messages.items.properties.content.maxLength')
         AS chat_content_maxLength_before,
       JSON_EXTRACT(param_schema, '$.properties.text.maxLength')
         AS summary_text_maxLength_before
FROM t_capability
WHERE is_deleted = 0
  AND (
    (code = 'chat-completions'
      AND JSON_EXTRACT(param_schema, '$.properties.messages.items.properties.content.maxLength') = 12000)
    OR
    (code = 'long-summary'
      AND JSON_EXTRACT(param_schema, '$.properties.text.maxLength') = 12000)
  );

-- 2) chat-completions：content.maxLength 12000 -> 48000。
UPDATE t_capability
SET param_schema = JSON_SET(
  param_schema,
  '$.properties.messages.items.properties.content.maxLength', 48000
)
WHERE is_deleted = 0
  AND code = 'chat-completions'
  AND JSON_EXTRACT(param_schema, '$.properties.messages.items.properties.content.maxLength') = 12000;

-- 3) long-summary：text.maxLength 12000 -> 48000。
UPDATE t_capability
SET param_schema = JSON_SET(param_schema, '$.properties.text.maxLength', 48000)
WHERE is_deleted = 0
  AND code = 'long-summary'
  AND JSON_EXTRACT(param_schema, '$.properties.text.maxLength') = 12000;

-- 4) 校验：三处上限必须一致（48000 / 48000 / 执行器常量）。
SELECT id, code, status, executor, openai_alias,
       JSON_EXTRACT(param_schema, '$.properties.messages.items.properties.content.maxLength')
         AS chat_content_maxLength_after,
       JSON_EXTRACT(param_schema, '$.properties.text.maxLength')
         AS summary_text_maxLength_after
FROM t_capability
WHERE is_deleted = 0
  AND code IN ('chat-completions', 'long-summary');
