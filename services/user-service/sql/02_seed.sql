SET NAMES utf8mb4;
-- user-service 演示数据：可重复导入，导入后回到已知状态。
-- 对应开发指南 13.2：至少 1 个测试用户与若干积分，保证拉下来就能演示闭环。
-- 仅供本地演示与联调，密码为公开的演示口令，不含任何真实密钥。
--
-- 三个账号的口令都是 demo123456，覆盖主链路与两个异常分支：
--   demo        余额 100  正常    → 主闭环（对话扣分成功）
--   demopoor    余额 0    正常    → 积分不足 3001
--   demodisabled 余额 50  已禁用  → 禁用用户 1005
--
-- 口令哈希使用与运行时一致的 PBKDF2-HMAC-SHA256（格式
-- pbkdf2_sha256$240000$salt_hex$hash_hex，见 app/core/password.py）。
USE user_db;

INSERT INTO t_user (id, username, password_hash, nickname, status)
VALUES
  (1, 'demo', 'pbkdf2_sha256$240000$3121a4f0c9b8e7d65f4a3b2c1d0e9f8a$e2f886b88a9cf2cd5cb96f92b0f19470cf8465279e8cdf997d1667be153a412e', '演示用户', 'normal'),
  (2, 'demopoor', 'pbkdf2_sha256$240000$3121a4f0c9b8e7d65f4a3b2c1d0e9f8a$e2f886b88a9cf2cd5cb96f92b0f19470cf8465279e8cdf997d1667be153a412e', '零积分用户', 'normal'),
  (3, 'demodisabled', 'pbkdf2_sha256$240000$3121a4f0c9b8e7d65f4a3b2c1d0e9f8a$e2f886b88a9cf2cd5cb96f92b0f19470cf8465279e8cdf997d1667be153a412e', '已禁用用户', 'disabled')
AS new
ON DUPLICATE KEY UPDATE
  password_hash = new.password_hash,
  nickname = new.nickname,
  status = new.status,
  is_deleted = 0;

INSERT INTO t_points_account (id, user_id, balance, frozen, version)
VALUES
  (1, 1, 100, 0, 1),
  (2, 2, 0, 0, 1),
  (3, 3, 50, 0, 1)
AS new
ON DUPLICATE KEY UPDATE
  balance = new.balance,
  frozen = new.frozen,
  version = new.version,
  is_deleted = 0;

INSERT INTO t_points_log
  (id, user_id, direction, amount, balance_after, biz_type, request_id, remark)
VALUES
  (1, 1, 'in', 100, 100, 'register', 'register-1', '注册赠送初始积分'),
  (2, 2, 'in', 0, 0, 'register', 'register-2', '注册赠送初始积分'),
  (3, 3, 'in', 50, 50, 'register', 'register-3', '注册赠送初始积分')
AS new
ON DUPLICATE KEY UPDATE
  amount = new.amount,
  balance_after = new.balance_after,
  remark = new.remark,
  is_deleted = 0;
