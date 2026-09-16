-- billing-service 演示数据：可重复导入，导入后回到已知状态。
-- 对应开发指南 13.2：保证拉下来即可演示“查用量”页面。
--
-- 演示用户与 user-service 的 02_seed.sql 保持一致：
--   user_id=1 demo（余额 100）、user_id=2 demopoor（余额 0）。
-- 明细只写 2 条 Mock 调用，日期固定为 2026-09-15，便于稳定断言；
-- 不含任何真实密钥。
USE billing_db;

INSERT INTO t_call_record
  (id, request_id, user_id, capability_id, service_name, cost, call_status, duration_ms, model_name, create_time)
VALUES
  (1, 'seed-demo-0001', 1, 1, 'ai-chat-service', 5, 'success', 320, 'mock-model', '2026-09-15 10:00:00'),
  (2, 'seed-demo-0002', 1, 1, 'ai-chat-service', 5, 'success', 280, 'mock-model', '2026-09-15 10:05:00')
AS new
ON DUPLICATE KEY UPDATE
  user_id = new.user_id,
  capability_id = new.capability_id,
  service_name = new.service_name,
  cost = new.cost,
  call_status = new.call_status,
  duration_ms = new.duration_ms,
  model_name = new.model_name,
  -- 明细时间必须与 t_usage_daily.stat_date 对齐，否则演示数据的“按天”
  -- 与“明细”两个口径会互相矛盾。
  create_time = new.create_time,
  is_deleted = 0;

INSERT INTO t_usage_daily (id, stat_date, user_id, capability_id, call_count, total_cost)
VALUES
  (1, '2026-09-15', 1, 1, 2, 10)
AS new
ON DUPLICATE KEY UPDATE
  call_count = new.call_count,
  total_cost = new.total_cost,
  is_deleted = 0;
