-- =============================================================================
-- 07_demo_seed.sql —— 演示环境种子（只服务于演示/答辩，不参与业务逻辑）
--
-- 为什么需要它：
--   部署基线（01~06）只建表 + 灌最小数据，直接起来是这样：
--     * t_model_provider 是空表      -> 「模型服务」页供应商区一片空白
--     * 只有 3 个能力，没有文生图     -> 能力市场和后台都少一张卡
--     * 能力描述还写着「支持 Mock 与真实模型；主闭环演示能力」
--                                    -> 答辩投屏时是减分项
--   本文件把库整理成「可上镜」状态，等价于开发机上人工调好的那套配置。
--
-- 幂等性：全部使用 INSERT ... ON DUPLICATE KEY UPDATE 与按 code 的 UPDATE，
--         重复执行结果一致，不会产生重复行。
--
-- 密钥说明（重要）：
--   api_key_cipher 是用 PROVIDER_MASTER_KEY_V1 加密后的密文，主密钥放在
--   deploy/.env（不入库、私下分发）。因此换机器时必须沿用同一个主密钥，
--   否则密文解不开、能力调用会失败；要换主密钥就得在后台重新录入供应商密钥。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) 上游供应商：保留 2 个真实可用的通道
-- -----------------------------------------------------------------------------

USE ai_chat_db;

INSERT INTO t_model_provider
  (id, name, alias, protocol, base_url, api_key_cipher, api_key_mask,
   default_model, timeout_ms, status, last_test_ok_at, is_deleted)
VALUES
  (155, 'DeepSeek', 'deepseek', 'openai-chat', 'https://api.deepseek.com/v1',
   'v1:WVhpwKCUH0EimljE:Zugg16YPDT0FPJd6Ub13dWpOJUMCusdFhvuV0OF1J54RDnUJtUgg4TFbqFKoZy6Di1KF',
   '********3bad', 'deepseek-flash', 60000, 'enabled', NOW(), 0),
  (251, 'DashScope 通义万相', 'dashscope-image', 'dashscope-image',
   'https://dashscope.aliyuncs.com',
   'v1:Rvjzu59U3Xprszfu:fdFQcP98rJKbzDpn1Yl7Wutm0M9nfreCZsVL0FY28Nkj9bcc5FmCTSBoEI2/dPyZfMKX8mMLSCfSjBevu56d9rYs4NkmN4NTGeju+d8Z7dbRWZhusDSelRek1yNgsHVKqskUsy38eEl0aZjhJtSAgPENOheBF9at+FlwcNEIVBMIFaAX',
   '********DuQk', 'wanx2.1-t2i-turbo', 90000, 'enabled', NOW(), 0)
AS new
ON DUPLICATE KEY UPDATE
  name           = new.name,
  protocol       = new.protocol,
  base_url       = new.base_url,
  api_key_cipher = new.api_key_cipher,
  api_key_mask   = new.api_key_mask,
  default_model  = new.default_model,
  timeout_ms     = new.timeout_ms,
  status         = new.status,
  last_test_ok_at = new.last_test_ok_at,
  is_deleted     = 0;

-- 清掉部署基线里可能残留的示例供应商（api.example.com），它们在界面上是噪音。
UPDATE t_model_provider
SET is_deleted = 1, status = 'disabled'
WHERE alias IN ('example-provider', 'enable-check', 'list-check', 'test-probe');

-- -----------------------------------------------------------------------------
-- 2) 能力目录：4 个能力，统一对外模型名与文案
-- -----------------------------------------------------------------------------

USE capability_db;

-- 2.1 文生图：部署基线里没有这条，补齐（开发库里它是后加的）。
INSERT INTO t_capability
  (id, category_id, name, code, openai_alias, service_name, path, param_schema,
   price_per_call, billing_mode, executor, provider_alias, max_output_tokens,
   exposed_to_market, status, description, is_deleted)
VALUES
  (2169, 2, '文生图', 'text-to-image', 'wanx-image', 'ai-chat-service',
   '/api/chat/completions',
   CAST('{"type":"object","required":["prompt"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":2000},"size":{"type":"string","enum":["1024*1024","1280*720","720*1280"]},"n":{"type":"integer","minimum":1,"maximum":4}},"additionalProperties":false}' AS JSON),
   20, 'per_call', 'image-generate', 'dashscope-image', 1024, 1, 'online',
   '根据文本提示词生成图片（DashScope 通义万相 wanx2.1）', 0)
AS new
ON DUPLICATE KEY UPDATE
  category_id      = new.category_id,
  name             = new.name,
  openai_alias     = new.openai_alias,
  service_name     = new.service_name,
  path             = new.path,
  param_schema     = new.param_schema,
  price_per_call   = new.price_per_call,
  billing_mode     = new.billing_mode,
  executor         = new.executor,
  provider_alias   = new.provider_alias,
  max_output_tokens = new.max_output_tokens,
  exposed_to_market = new.exposed_to_market,
  status           = new.status,
  description      = new.description,
  is_deleted       = 0;

-- 2.2 多轮对话：默认走全局配置。
--     注意 provider_alias 这里刻意留空：供应商是**环境相关**的，CI 用本地模型
--     替身（MODEL_BASE_URL 指向替身进程），一旦绑定到 api.deepseek.com 就会绕过
--     替身，e2e 的 model_invocations 直接为 0 并报 4002。
--     演示环境需要「被 1 个能力引用」的展示效果时，启动后单独执行
--     deploy/demo/bind_chat_provider.sql（不进 init，CI 不会跑到）。
UPDATE t_capability
SET name = '多轮对话',
    openai_alias = 'deepseek-chat',
    executor = 'chat',
    provider_alias = '',
    price_per_call = 5,
    billing_mode = 'per_call',
    max_output_tokens = 1024,
    exposed_to_market = 1,
    status = 'online',
    description = '多轮对话与文本生成，支持上下文记忆与流式输出'
WHERE code = 'chat-completions' AND is_deleted = 0;

-- 2.3 长文本摘要：保持走全局默认。
--     注意：summary 执行器叠加供应商通道会静默降级成兜底文案（已实测），
--     演示环境刻意不绑 provider_alias，改了会踩坑。
UPDATE t_capability
SET name = '长文本摘要',
    openai_alias = 'deepseek-summary',
    executor = 'summary',
    provider_alias = '',
    price_per_call = 3,
    billing_mode = 'per_call',
    max_output_tokens = 1024,
    exposed_to_market = 1,
    status = 'online',
    description = '把长文档压缩为结论与行动项，适用于报告与会议纪要'
WHERE code = 'long-summary' AND is_deleted = 0;

-- 2.4 视觉理解：展示位。对外模型名照填（后台好看），但两处都要管住：
--     1) exposed_to_market = 0 —— 它进不了能力市场。市场的过滤条件是
--        status=online AND exposed_to_market=1，二者是独立开关；保留 online
--        是为了让它继续出现在运营后台，只是不对外展示。
--     2) 入参 required 是 image_url 而不是 messages，所以即便填了别名，
--        发布门禁也会把它挡在 /v1/models 之外。
--     现场不要点它的「去调试」，多模态通道尚未接入。
UPDATE t_capability
SET name = '视觉理解',
    openai_alias = 'deepseek-vision',
    executor = 'chat',
    provider_alias = '',
    price_per_call = 8,
    billing_mode = 'per_call',
    max_output_tokens = 1024,
    exposed_to_market = 0,
    status = 'online',
    description = '图片内容识别与结构化提取（多模态通道接入后开放）'
WHERE code = 'vision-parse' AND is_deleted = 0;

-- -----------------------------------------------------------------------------
-- 3) 演示账号：余额归位，保证反复彩排后仍够演示
-- -----------------------------------------------------------------------------

USE user_db;

UPDATE t_points_account SET balance = 100, frozen = 0 WHERE user_id = 1;
UPDATE t_user SET status = 'normal' WHERE id = 1;

-- -----------------------------------------------------------------------------
-- 4) 自检：把关键结果打出来，启动日志里能直接看到
-- -----------------------------------------------------------------------------

SELECT '=== 供应商（未删除） ===' AS section;
SELECT id, name, alias, protocol, status
FROM ai_chat_db.t_model_provider
WHERE is_deleted = 0
ORDER BY id;

SELECT '=== 能力（未删除） ===' AS section;
SELECT id, name, code, openai_alias,
       COALESCE(NULLIF(provider_alias, ''), '(全局默认)') AS provider,
       price_per_call, executor, status, exposed_to_market
FROM capability_db.t_capability
WHERE is_deleted = 0
ORDER BY id;

SELECT '=== 演示账号 ===' AS section;
SELECT u.id, u.username, u.status, p.balance
FROM user_db.t_user u
JOIN user_db.t_points_account p ON p.user_id = u.id
WHERE u.id = 1;
