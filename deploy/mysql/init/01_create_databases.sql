SET NAMES utf8mb4;
-- MySQL 容器首次初始化时创建四个相互隔离的业务库。
CREATE DATABASE IF NOT EXISTS `user_db`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS `capability_db`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS `billing_db`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE DATABASE IF NOT EXISTS `ai_chat_db`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
