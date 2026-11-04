-- =============================================================================
-- 演示态绑定：把「多轮对话」挂到 DeepSeek 供应商通道
--
-- 为什么单独一个文件，而不写进 deploy/mysql/init/07_demo_seed.sql：
--   供应商是**环境相关**的。CI 用本地模型替身（MODEL_BASE_URL 指向替身进程），
--   一旦能力绑定了 api.deepseek.com，请求就会绕过替身直接打外网，
--   e2e 的 model_invocations 变成 0 并报 4002「下游服务不可用」。
--   所以建库种子只准备供应商档案（不绑定），演示环境在启动后执行本文件，
--   让运营后台的「影响面」列显示「被 1 个能力引用」。
--
-- 前置条件：
--   1) deploy/.env 的 PROVIDER_MASTER_KEY_V1 必须与 07 种子里供应商密文匹配
--      （演示交接时沿用组长给的那份 .env，不要重新生成）；
--   2) 可选：先在后台点一次 DeepSeek 的「测试」确认通道可用。
--
-- 幂等：重复执行结果一致。
-- 回滚：UPDATE capability_db.t_capability SET provider_alias='' WHERE code='chat-completions';
-- =============================================================================

USE capability_db;

UPDATE t_capability
SET provider_alias = 'deepseek'
WHERE code = 'chat-completions'
  AND is_deleted = 0;

SELECT '=== 演示绑定结果 ===' AS section;
SELECT id, name, code, provider_alias,
       COALESCE(NULLIF(provider_alias, ''), '(全局默认)') AS provider
FROM t_capability
WHERE is_deleted = 0
ORDER BY id;

SELECT '=== 供应商影响面 ===' AS section;
SELECT p.name, p.alias, p.status,
       COUNT(c.id) AS referenced_capabilities
FROM ai_chat_db.t_model_provider p
LEFT JOIN t_capability c
       ON c.provider_alias = p.alias AND c.is_deleted = 0
WHERE p.is_deleted = 0
GROUP BY p.id, p.name, p.alias, p.status
ORDER BY p.id;
