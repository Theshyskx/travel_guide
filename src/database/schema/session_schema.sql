-- 会话管理模块数据库表结构
-- 数据库: travel_guide

-- 1. 会话会话表
CREATE TABLE IF NOT EXISTS `conversation_session` (
    `session_id` VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '会话唯一标识',
    `user_id` VARCHAR(64) DEFAULT NULL COMMENT '用户ID（匿名用户为临时标识）',
    `title` VARCHAR(255) DEFAULT '新对话' COMMENT '会话标题',
    `current_state` VARCHAR(64) DEFAULT 'idle' COMMENT '当前对话状态',
    `state_data` JSON DEFAULT NULL COMMENT '状态相关数据',
    `history_summary` TEXT DEFAULT NULL COMMENT '历史消息摘要',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `last_active_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活跃时间',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否激活',
    `message_count` INT NOT NULL DEFAULT 0 COMMENT '消息总数',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_create_time` (`create_time`),
    INDEX `idx_last_active_time` (`last_active_time`),
    INDEX `idx_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话会话表';

-- 2. 会话消息表
CREATE TABLE IF NOT EXISTS `conversation_message` (
    `message_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '消息唯一标识',
    `session_id` VARCHAR(64) NOT NULL COMMENT '所属会话ID',
    `role` ENUM('system', 'user', 'assistant') NOT NULL COMMENT '消息角色',
    `content` TEXT NOT NULL COMMENT '消息内容',
    `metadata` JSON DEFAULT NULL COMMENT '消息元数据',
    `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '消息时间戳',
    `sequence_num` INT NOT NULL COMMENT '消息序号',
    INDEX `idx_session_id` (`session_id`),
    INDEX `idx_timestamp` (`timestamp`),
    INDEX `idx_sequence_num` (`sequence_num`),
    FOREIGN KEY (`session_id`) REFERENCES `conversation_session`(`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话消息表';

-- 3. 初始化会话过期清理事件（可选，每天执行一次）
-- DELIMITER //
-- CREATE EVENT IF NOT EXISTS `cleanup_expired_sessions`
-- ON SCHEDULE EVERY 1 DAY
-- STARTS CURRENT_TIMESTAMP
-- DO
-- BEGIN
--     -- 删除30天未活跃的会话
--     DELETE FROM conversation_message
--     WHERE session_id IN (
--         SELECT session_id FROM conversation_session
--         WHERE last_active_time < DATE_SUB(NOW(), INTERVAL 30 DAY)
--     );
--     DELETE FROM conversation_session
--     WHERE last_active_time < DATE_SUB(NOW(), INTERVAL 30 DAY);
-- END //
-- DELIMITER ;
