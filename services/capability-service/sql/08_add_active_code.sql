SET NAMES utf8mb4;
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
