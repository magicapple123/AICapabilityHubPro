-- capability-service 演示数据：可重复导入，导入后回到已知状态。
-- 对应开发指南 13.2 与接口契约第 7 节：2 个分类 + 3 个能力（其中 1 个对话能力 online）。
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
      'properties', JSON_OBJECT('messages', JSON_OBJECT('type', 'array')),
      'required', JSON_ARRAY('messages')
    ),
    5, 'online', '多轮对话与文本生成，支持 Mock 与真实模型；主闭环演示能力'
  ),
  (
    2, 1, '长文本摘要', 'long-summary', 'ai-chat-service', '/api/chat/completions',
    JSON_OBJECT(
      'type', 'object',
      'properties', JSON_OBJECT('text', JSON_OBJECT('type', 'string')),
      'required', JSON_ARRAY('text')
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
