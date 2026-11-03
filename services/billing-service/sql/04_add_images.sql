SET NAMES utf8mb4;
-- billing-service 增量迁移（D3 文生图：调用记录带图片产物）。
--
-- 为什么要在 billing 侧存：需求 D3 要求"调用记录可预览图片"，
-- 而 ai-chat 只把收据回给当次请求方，历史调用要在 billing 的明细里能看到图。
--
-- 只增列，不动任何既有列；旧记录该列为 NULL，语义是"没有图片产物"，
-- 与"有图片产物但列表为空"通过 JSON 类型区分（本服务写入时值为数组）。
-- 重复执行安全（MySQL 不支持 ADD COLUMN IF NOT EXISTS，用 information_schema 判断）。

USE billing_db;

SET @exists := (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = 'billing_db'
    AND TABLE_NAME = 't_call_record'
    AND COLUMN_NAME = 'images'
);
SET @ddl := IF(
  @exists = 0,
  'ALTER TABLE t_call_record ADD COLUMN images JSON NULL COMMENT ''图片产物列表 [{url, revised_prompt}]，仅文生图有值'' AFTER model_name',
  'SELECT ''t_call_record.images already exists'' AS skipped'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 迁移自检：列已存在，且历史行全部为 NULL（不伪造数据）。
SELECT COUNT(*) AS total_rows,
       SUM(images IS NULL) AS rows_without_images
FROM t_call_record;
