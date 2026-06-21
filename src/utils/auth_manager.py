import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import pymysql
from pymysql.cursors import DictCursor
from src.config.settings import config
import bcrypt

class AuthManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        self._host = config.DB_HOST
        self._port = config.DB_PORT
        self._user = config.DB_USER
        self._password = config.DB_PASSWORD
        self._database = config.DB_NAME

    def _get_connection(self):
        return pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            charset='utf8mb4',
            cursorclass=DictCursor,
            autocommit=False
        )

    async def initialize(self):
        await self._ensure_tables_exist()
        await self._create_default_admin()
        print("AuthManager 初始化完成")

    async def _ensure_tables_exist(self):
        create_users_table = """
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
        """

        create_admins_table = """
        CREATE TABLE IF NOT EXISTS `admins` (
            `admin_id` VARCHAR(64) NOT NULL PRIMARY KEY,
            `user_id` VARCHAR(64) NOT NULL,
            `permissions` JSON DEFAULT NULL,
            `department` VARCHAR(100) DEFAULT NULL,
            `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (`user_id`) REFERENCES `users`(`user_id`) ON DELETE CASCADE,
            UNIQUE INDEX `idx_user_id` (`user_id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """

        def _do_create():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(create_users_table)
                    cursor.execute(create_admins_table)
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_create)

    async def _create_default_admin(self):
        def _do_create():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT user_id FROM users WHERE user_id = 'admin'")
                    if not cursor.fetchone():
                        password_hash = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        cursor.execute("""
                            INSERT INTO users (user_id, password_hash, username, role, is_active, create_time)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, ('admin', password_hash, '系统管理员', 'admin', 1, datetime.now()))

                        cursor.execute("""
                            INSERT INTO admins (admin_id, user_id, permissions, department, create_time)
                            VALUES (%s, %s, %s, %s, %s)
                        """, ('admin', 'admin', '["all"]', '系统管理', datetime.now()))
                        conn.commit()
                        print("默认管理员账户已创建: admin / admin123")
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_create)

    def _hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

    async def register(self, user_id: str, password: str, username: Optional[str] = None, role: str = 'user') -> Dict[str, Any]:
        def _do_register():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
                    if cursor.fetchone():
                        return {"success": False, "message": "用户ID已存在"}

                    password_hash = self._hash_password(password)

                    cursor.execute("""
                        INSERT INTO users (user_id, password_hash, username, role, is_active, create_time)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (user_id, password_hash, username or user_id, role, 1, datetime.now()))

                    if role == 'admin':
                        cursor.execute("""
                            INSERT INTO admins (admin_id, user_id, permissions, department, create_time)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (user_id, user_id, '["all"]', '系统管理', datetime.now()))

                    conn.commit()
                    return {"success": True, "message": "注册成功", "user_id": user_id, "role": role}
            except Exception as e:
                conn.rollback()
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_register)

    async def login(self, user_id: str, password: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Dict[str, Any]:
        def _do_login():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                    user = cursor.fetchone()

                    if not user:
                        self._log_login(user_id, None, 'login', ip_address, user_agent, 0, '用户不存在')
                        return {"success": False, "message": "用户不存在"}

                    if not user['is_active']:
                        self._log_login(user_id, user.get('username'), 'login', ip_address, user_agent, 0, '账户已被禁用')
                        return {"success": False, "message": "账户已被禁用"}

                    if not self._verify_password(password, user['password_hash']):
                        self._log_login(user_id, user.get('username'), 'login', ip_address, user_agent, 0, '密码错误')
                        return {"success": False, "message": "密码错误"}

                    cursor.execute("""
                        UPDATE users SET last_login_time = %s, last_login_ip = %s WHERE user_id = %s
                    """, (datetime.now(), ip_address, user_id))
                    conn.commit()

                    self._log_login(user_id, user.get('username'), 'login', ip_address, user_agent, 1, None)

                    return {
                        "success": True,
                        "message": "登录成功",
                        "user": {
                            "user_id": user['user_id'],
                            "username": user.get('username'),
                            "role": user['role']
                        }
                    }
            except Exception as e:
                return {"success": False, "message": str(e)}
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_login)

    def _log_login(self, user_id: str, username: Optional[str], login_type: str, ip_address: Optional[str], user_agent: Optional[str], status: int, fail_reason: Optional[str]):
        try:
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO login_logs (user_id, username, login_type, ip_address, user_agent, login_status, fail_reason, create_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (user_id, username, login_type, ip_address, user_agent, status, fail_reason, datetime.now()))
                conn.commit()
            finally:
                conn.close()
        except:
            pass

    async def logout(self, user_id: str, ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> Dict[str, Any]:
        def _do_logout():
            try:
                self._log_login(user_id, None, 'logout', ip_address, user_agent, 1, None)
                return {"success": True, "message": "登出成功"}
            except Exception as e:
                return {"success": False, "message": str(e)}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_logout)

    async def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        def _do_get():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT user_id, username, email, phone, role, is_active, create_time, last_login_time, last_login_ip
                        FROM users WHERE user_id = %s
                    """, (user_id,))
                    user = cursor.fetchone()
                    if user:
                        user.pop('password_hash', None)
                    return user
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_get)

    async def get_all_users(self, role: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        def _do_get():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    if role:
                        cursor.execute("""
                            SELECT user_id, username, email, phone, role, is_active, create_time, last_login_time, last_login_ip
                            FROM users WHERE role = %s ORDER BY create_time DESC LIMIT %s OFFSET %s
                        """, (role, limit, offset))
                    else:
                        cursor.execute("""
                            SELECT user_id, username, email, phone, role, is_active, create_time, last_login_time, last_login_ip
                            FROM users ORDER BY create_time DESC LIMIT %s OFFSET %s
                        """, (limit, offset))
                    return cursor.fetchall()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_get)

auth_manager = AuthManager()
