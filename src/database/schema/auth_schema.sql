-- 用户认证模块数据库表结构
-- 数据库: travel_guide

-- 1. 用户表
CREATE TABLE IF NOT EXISTS `users` (
    `user_id` VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '用户ID（登录账号）',
    `password_hash` VARCHAR(255) NOT NULL COMMENT '密码哈希',
    `username` VARCHAR(100) DEFAULT NULL COMMENT '用户名/昵称',
    `email` VARCHAR(255) DEFAULT NULL COMMENT '邮箱',
    `phone` VARCHAR(20) DEFAULT NULL COMMENT '手机号',
    `role` ENUM('user', 'admin') NOT NULL DEFAULT 'user' COMMENT '用户角色',
    `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否激活',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `last_login_time` DATETIME DEFAULT NULL COMMENT '最后登录时间',
    `last_login_ip` VARCHAR(50) DEFAULT NULL COMMENT '最后登录IP',
    INDEX `idx_role` (`role`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- 2. 管理员表（扩展用户表，用于管理员特定信息）
CREATE TABLE IF NOT EXISTS `admins` (
    `admin_id` VARCHAR(64) NOT NULL PRIMARY KEY COMMENT '管理员ID',
    `user_id` VARCHAR(64) NOT NULL COMMENT '关联用户ID',
    `permissions` JSON DEFAULT NULL COMMENT '权限列表',
    `department` VARCHAR(100) DEFAULT NULL COMMENT '所属部门',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
    UNIQUE INDEX `idx_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='管理员表';

-- 3. 系统日志表
CREATE TABLE IF NOT EXISTS `system_logs` (
    `log_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '日志ID',
    `user_id` VARCHAR(64) DEFAULT NULL COMMENT '操作用户ID',
    `username` VARCHAR(100) DEFAULT NULL COMMENT '操作用户名',
    `action` VARCHAR(100) NOT NULL COMMENT '操作类型',
    `resource` VARCHAR(100) DEFAULT NULL COMMENT '操作资源',
    `method` VARCHAR(10) DEFAULT NULL COMMENT '请求方法',
    `path` VARCHAR(500) DEFAULT NULL COMMENT '请求路径',
    `ip_address` VARCHAR(50) DEFAULT NULL COMMENT 'IP地址',
    `user_agent` TEXT DEFAULT NULL COMMENT '用户代理',
    `request_params` JSON DEFAULT NULL COMMENT '请求参数',
    `response_status` INT DEFAULT NULL COMMENT '响应状态码',
    `error_message` TEXT DEFAULT NULL COMMENT '错误信息',
    `execution_time` FLOAT DEFAULT NULL COMMENT '执行时间(毫秒)',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '日志时间',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_action` (`action`),
    INDEX `idx_resource` (`resource`),
    INDEX `idx_create_time` (`create_time`),
    INDEX `idx_ip_address` (`ip_address`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统日志表';

-- 4. 登录日志表
CREATE TABLE IF NOT EXISTS `login_logs` (
    `log_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY COMMENT '日志ID',
    `user_id` VARCHAR(64) NOT NULL COMMENT '登录用户ID',
    `username` VARCHAR(100) DEFAULT NULL COMMENT '登录用户名',
    `login_type` ENUM('login', 'logout', 'register') NOT NULL COMMENT '登录类型',
    `ip_address` VARCHAR(50) DEFAULT NULL COMMENT 'IP地址',
    `user_agent` TEXT DEFAULT NULL COMMENT '用户代理',
    `login_status` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '登录状态（1成功，0失败）',
    `fail_reason` VARCHAR(255) DEFAULT NULL COMMENT '失败原因',
    `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '登录时间',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_login_type` (`login_type`),
    INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='登录日志表';

-- 5. 插入默认管理员账户（密码: admin123）
-- 密码使用 bcrypt 哈希，这里是简单的占位符，实际使用时会通过代码创建
INSERT INTO `users` (`user_id`, `password_hash`, `username`, `role`, `is_active`)
VALUES ('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewKyDAv0F4aFUJ3G', '系统管理员', 'admin', 1)
ON DUPLICATE KEY UPDATE username = '系统管理员';

INSERT INTO `admins` (`admin_id`, `user_id`, `permissions`, `department`)
VALUES ('admin', 'admin', '["all"]', '系统管理')
ON DUPLICATE KEY UPDATE department = '系统管理';
