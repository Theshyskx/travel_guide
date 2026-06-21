import pymysql
import bcrypt
from src.config.settings import config

conn = pymysql.connect(
    host=config.DB_HOST,
    port=config.DB_PORT,
    user=config.DB_USER,
    password=config.DB_PASSWORD,
    database=config.DB_NAME,
    charset='utf8mb4'
)

try:
    with conn.cursor() as cursor:
        print("Creating users table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `users` (
                `user_id` VARCHAR(64) NOT NULL PRIMARY KEY,
                `password_hash` VARCHAR(255) NOT NULL,
                `username` VARCHAR(100) DEFAULT NULL,
                `email` VARCHAR(255) DEFAULT NULL,
                `phone` VARCHAR(20) DEFAULT NULL,
                `role` ENUM('user', 'admin') NOT NULL DEFAULT 'user',
                `is_active` TINYINT(1) NOT NULL DEFAULT 1,
                `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                `last_login_time` DATETIME DEFAULT NULL,
                `last_login_ip` VARCHAR(50) DEFAULT NULL,
                INDEX `idx_role` (`role`),
                INDEX `idx_create_time` (`create_time`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("[OK] users table created")

        print("Creating admins table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `admins` (
                `admin_id` VARCHAR(64) NOT NULL PRIMARY KEY,
                `user_id` VARCHAR(64) NOT NULL,
                `permissions` JSON DEFAULT NULL,
                `department` VARCHAR(100) DEFAULT NULL,
                `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
                UNIQUE INDEX `idx_user_id` (`user_id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("[OK] admins table created")

        print("Creating system_logs table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `system_logs` (
                `log_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                `user_id` VARCHAR(64) DEFAULT NULL,
                `username` VARCHAR(100) DEFAULT NULL,
                `action` VARCHAR(100) NOT NULL,
                `resource` VARCHAR(100) DEFAULT NULL,
                `method` VARCHAR(10) DEFAULT NULL,
                `path` VARCHAR(500) DEFAULT NULL,
                `ip_address` VARCHAR(50) DEFAULT NULL,
                `user_agent` TEXT DEFAULT NULL,
                `request_params` JSON DEFAULT NULL,
                `response_status` INT DEFAULT NULL,
                `error_message` TEXT DEFAULT NULL,
                `execution_time` FLOAT DEFAULT NULL,
                `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX `idx_user_id` (`user_id`),
                INDEX `idx_action` (`action`),
                INDEX `idx_resource` (`resource`),
                INDEX `idx_create_time` (`create_time`),
                INDEX `idx_ip_address` (`ip_address`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("[OK] system_logs table created")

        print("Creating login_logs table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS `login_logs` (
                `log_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                `user_id` VARCHAR(64) NOT NULL,
                `username` VARCHAR(100) DEFAULT NULL,
                `login_type` ENUM('login', 'logout', 'register') NOT NULL,
                `ip_address` VARCHAR(50) DEFAULT NULL,
                `user_agent` TEXT DEFAULT NULL,
                `login_status` TINYINT(1) NOT NULL DEFAULT 1,
                `fail_reason` VARCHAR(255) DEFAULT NULL,
                `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX `idx_user_id` (`user_id`),
                INDEX `idx_login_type` (`login_type`),
                INDEX `idx_create_time` (`create_time`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        print("[OK] login_logs table created")

        conn.commit()

        print("\nChecking/creating default admin account...")
        cursor.execute("SELECT user_id FROM users WHERE user_id = 'admin'")
        if cursor.fetchone():
            print("[OK] Admin account already exists (admin)")
        else:
            password_hash = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cursor.execute("""
                INSERT INTO users (user_id, password_hash, username, role, is_active, create_time)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, ('admin', password_hash, 'System Admin', 'admin', 1))

            cursor.execute("""
                INSERT INTO admins (admin_id, user_id, permissions, department, create_time)
                VALUES (%s, %s, %s, %s, NOW())
            """, ('admin', 'admin', '["all"]', 'System Management'))

            conn.commit()
            print("[OK] Default admin account created: admin / admin123")

        print("\nAll tables created successfully!")

finally:
    conn.close()
