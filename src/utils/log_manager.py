import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import pymysql
from pymysql.cursors import DictCursor
from src.config.settings import config

class LogManager:
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
        await self._ensure_table_exists()
        print("LogManager 初始化完成")

    async def _ensure_table_exists(self):
        create_logs_table = """
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
        """

        def _do_create():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(create_logs_table)
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_create)

    async def log(self, action: str, user_id: Optional[str] = None, username: Optional[str] = None,
                  resource: Optional[str] = None, method: Optional[str] = None, path: Optional[str] = None,
                  ip_address: Optional[str] = None, user_agent: Optional[str] = None,
                  request_params: Optional[Dict[str, Any]] = None, response_status: Optional[int] = None,
                  error_message: Optional[str] = None, execution_time: Optional[float] = None):
        def _do_log():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO system_logs 
                        (user_id, username, action, resource, method, path, ip_address, user_agent, request_params, response_status, error_message, execution_time, create_time)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        user_id, username, action, resource, method, path, ip_address, user_agent,
                        json.dumps(request_params, ensure_ascii=False) if request_params else None,
                        response_status, error_message, execution_time, datetime.now()
                    ))
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_log)

    async def get_logs(self, user_id: Optional[str] = None, action: Optional[str] = None,
                        resource: Optional[str] = None, start_time: Optional[datetime] = None,
                        end_time: Optional[datetime] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        def _do_get():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    query = "SELECT * FROM system_logs WHERE 1=1"
                    params = []

                    if user_id:
                        query += " AND user_id = %s"
                        params.append(user_id)
                    if action:
                        query += " AND action = %s"
                        params.append(action)
                    if resource:
                        query += " AND resource = %s"
                        params.append(resource)
                    if start_time:
                        query += " AND create_time >= %s"
                        params.append(start_time)
                    if end_time:
                        query += " AND create_time <= %s"
                        params.append(end_time)

                    query += " ORDER BY create_time DESC LIMIT %s OFFSET %s"
                    params.extend([limit, offset])

                    cursor.execute(query, params)
                    return cursor.fetchall()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_get)

    async def get_log_count(self, user_id: Optional[str] = None, action: Optional[str] = None,
                            resource: Optional[str] = None, start_time: Optional[datetime] = None,
                            end_time: Optional[datetime] = None) -> int:
        def _do_count():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    query = "SELECT COUNT(*) as total FROM system_logs WHERE 1=1"
                    params = []

                    if user_id:
                        query += " AND user_id = %s"
                        params.append(user_id)
                    if action:
                        query += " AND action = %s"
                        params.append(action)
                    if resource:
                        query += " AND resource = %s"
                        params.append(resource)
                    if start_time:
                        query += " AND create_time >= %s"
                        params.append(start_time)
                    if end_time:
                        query += " AND create_time <= %s"
                        params.append(end_time)

                    cursor.execute(query, params)
                    return cursor.fetchone()['total']
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_count)

    async def get_login_logs(self, user_id: Optional[str] = None, login_type: Optional[str] = None,
                              start_time: Optional[datetime] = None, end_time: Optional[datetime] = None,
                              limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        def _do_get():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
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
                    conn.commit()

                    query = "SELECT * FROM login_logs WHERE 1=1"
                    params = []

                    if user_id:
                        query += " AND user_id = %s"
                        params.append(user_id)
                    if login_type:
                        query += " AND login_type = %s"
                        params.append(login_type)
                    if start_time:
                        query += " AND create_time >= %s"
                        params.append(start_time)
                    if end_time:
                        query += " AND create_time <= %s"
                        params.append(end_time)

                    query += " ORDER BY create_time DESC LIMIT %s OFFSET %s"
                    params.extend([limit, offset])

                    cursor.execute(query, params)
                    return cursor.fetchall()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_get)

    async def delete_old_logs(self, days: int = 30) -> int:
        def _do_delete():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        DELETE FROM system_logs WHERE create_time < DATE_SUB(NOW(), INTERVAL %s DAY)
                    """, (days,))
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_delete)

log_manager = LogManager()
