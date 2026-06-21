import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
import pymysql
from pymysql.cursors import DictCursor
from src.config.settings import config
from cachetools import TTLCache

class ConversationState(Enum):
    IDLE = "idle"
    WAITING_DESTINATION = "waiting_destination"
    WAITING_BUDGET = "waiting_budget"
    WAITING_PREFERENCES = "waiting_preferences"
    PROCESSING = "processing"
    COMPLETED = "completed"

@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else self.timestamp,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now()
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=timestamp,
            metadata=data.get("metadata")
        )

@dataclass
class ConversationSession:
    session_id: str
    user_id: Optional[str] = None
    title: str = "新对话"
    current_state: ConversationState = ConversationState.IDLE
    state_data: Dict[str, Any] = field(default_factory=dict)
    history: List[Message] = field(default_factory=list)
    history_summary: Optional[str] = None
    create_time: datetime = field(default_factory=datetime.now)
    last_active_time: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    message_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "title": self.title,
            "current_state": self.current_state.value if isinstance(self.current_state, ConversationState) else self.current_state,
            "state_data": self.state_data,
            "history": [msg.to_dict() for msg in self.history],
            "history_summary": self.history_summary,
            "create_time": self.create_time.isoformat() if isinstance(self.create_time, datetime) else self.create_time,
            "last_active_time": self.last_active_time.isoformat() if isinstance(self.last_active_time, datetime) else self.last_active_time,
            "is_active": self.is_active,
            "message_count": self.message_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationSession':
        create_time = data.get("create_time")
        if isinstance(create_time, str):
            create_time = datetime.fromisoformat(create_time)
        elif create_time is None:
            create_time = datetime.now()

        last_active_time = data.get("last_active_time")
        if isinstance(last_active_time, str):
            last_active_time = datetime.fromisoformat(last_active_time)
        elif last_active_time is None:
            last_active_time = datetime.now()

        current_state = data.get("current_state", "idle")
        if isinstance(current_state, str):
            current_state = ConversationState(current_state)

        messages = data.get("history", [])
        history = [Message.from_dict(msg) if isinstance(msg, dict) else msg for msg in messages]

        return cls(
            session_id=data["session_id"],
            user_id=data.get("user_id"),
            title=data.get("title", "新对话"),
            current_state=current_state,
            state_data=data.get("state_data", {}),
            history=history,
            history_summary=data.get("history_summary"),
            create_time=create_time,
            last_active_time=last_active_time,
            is_active=data.get("is_active", True),
            message_count=data.get("message_count", len(history))
        )

class ConversationManager:
    _instance = None
    _lock = asyncio.Lock()

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

        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=1800)
        self._window_size = 10
        self._summary_threshold = 15
        self._cache_expiry_minutes = 30

        self._background_task: Optional[asyncio.Task] = None
        self._running = False

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
        self._running = True
        self._background_task = asyncio.create_task(self._cache_cleanup_loop())
        await self._ensure_tables_exist()
        print("ConversationManager 初始化完成")

    async def shutdown(self):
        self._running = False
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        await self._flush_all_caches()
        print("ConversationManager 已关闭")

    async def _ensure_tables_exist(self):
        create_session_table = """
        CREATE TABLE IF NOT EXISTS `conversation_session` (
            `session_id` VARCHAR(64) NOT NULL PRIMARY KEY,
            `user_id` VARCHAR(64) DEFAULT NULL,
            `title` VARCHAR(255) DEFAULT '新对话',
            `current_state` VARCHAR(64) DEFAULT 'idle',
            `state_data` JSON DEFAULT NULL,
            `history_summary` TEXT DEFAULT NULL,
            `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `last_active_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            `is_active` TINYINT(1) NOT NULL DEFAULT 1,
            `message_count` INT NOT NULL DEFAULT 0,
            INDEX `idx_user_id` (`user_id`),
            INDEX `idx_create_time` (`create_time`),
            INDEX `idx_last_active_time` (`last_active_time`),
            INDEX `idx_is_active` (`is_active`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """

        create_message_table = """
        CREATE TABLE IF NOT EXISTS `conversation_message` (
            `message_id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            `session_id` VARCHAR(64) NOT NULL,
            `role` ENUM('system', 'user', 'assistant') NOT NULL,
            `content` TEXT NOT NULL,
            `metadata` JSON DEFAULT NULL,
            `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `sequence_num` INT NOT NULL,
            INDEX `idx_session_id` (`session_id`),
            INDEX `idx_timestamp` (`timestamp`),
            INDEX `idx_sequence_num` (`sequence_num`),
            FOREIGN KEY (`session_id`) REFERENCES `conversation_session`(`session_id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._execute_ddl(create_session_table))
        await loop.run_in_executor(None, lambda: self._execute_ddl(create_message_table))

    def _execute_ddl(self, query: str):
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
            conn.commit()
        finally:
            conn.close()

    async def _cache_cleanup_loop(self):
        while self._running:
            try:
                await asyncio.sleep(300)
                await self._cleanup_expired_cache()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"缓存清理错误: {e}")

    async def _cleanup_expired_cache(self):
        now = datetime.now()
        expired_keys = []
        for session_id, session in self._cache.items():
            if (now - session.last_active_time).total_seconds() > self._cache_expiry_minutes * 60:
                expired_keys.append(session_id)

        for session_id in expired_keys:
            await self._persist_session(session_id)
            self._cache.pop(session_id, None)

    async def _flush_all_caches(self):
        for session_id in list(self._cache.keys()):
            await self._persist_session(session_id)
        self._cache.clear()

    async def _persist_session(self, session: Union[ConversationSession, str]):
        if isinstance(session, str):
            session = self._cache.get(session)
            if not session:
                return

        query = """
        INSERT INTO conversation_session
        (session_id, user_id, title, current_state, state_data, history_summary, create_time, last_active_time, is_active, message_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
        user_id = VALUES(user_id),
        title = VALUES(title),
        current_state = VALUES(current_state),
        state_data = VALUES(state_data),
        history_summary = VALUES(history_summary),
        last_active_time = VALUES(last_active_time),
        is_active = VALUES(is_active),
        message_count = VALUES(message_count)
        """

        state_value = session.current_state.value if isinstance(session.current_state, ConversationState) else session.current_state

        params = (
            session.session_id,
            session.user_id,
            session.title,
            state_value,
            json.dumps(session.state_data, ensure_ascii=False),
            session.history_summary,
            session.create_time,
            session.last_active_time,
            session.is_active,
            session.message_count
        )

        def _do_persist():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    cursor.execute("DELETE FROM conversation_message WHERE session_id = %s", (session.session_id,))
                    for idx, msg in enumerate(session.history):
                        cursor.execute("""
                        INSERT INTO conversation_message (session_id, role, content, metadata, timestamp, sequence_num)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            session.session_id,
                            msg.role,
                            msg.content,
                            json.dumps(msg.metadata, ensure_ascii=False) if msg.metadata else None,
                            msg.timestamp,
                            idx
                        ))
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_persist)

    async def create_session(self, session_id: str, user_id: Optional[str] = None, title: str = "新对话") -> ConversationSession:
        session = ConversationSession(
            session_id=session_id,
            user_id=user_id,
            title=title,
            create_time=datetime.now(),
            last_active_time=datetime.now()
        )
        self._cache[session_id] = session

        query = """
        INSERT INTO conversation_session (session_id, user_id, title, create_time, last_active_time, message_count)
        VALUES (%s, %s, %s, %s, %s, 0)
        ON DUPLICATE KEY UPDATE
        user_id = VALUES(user_id),
        title = VALUES(title),
        last_active_time = VALUES(last_active_time)
        """

        def _do_create():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (session_id, user_id, title, session.create_time, session.last_active_time))
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_create)
        return session

    async def get_session(self, session_id: str) -> Optional[ConversationSession]:
        if session_id in self._cache:
            session = self._cache[session_id]
            # 不在获取会话时更新 last_active_time，避免缓存和数据库不一致
            return session

        query = "SELECT * FROM conversation_session WHERE session_id = %s"
        messages_query = "SELECT * FROM conversation_message WHERE session_id = %s ORDER BY sequence_num"

        def _do_load():
            conn = self._get_connection()
            session_data = None
            messages = []
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (session_id,))
                    session_data = cursor.fetchone()

                    if session_data and session_data.get('state_data'):
                        if isinstance(session_data['state_data'], str):
                            session_data['state_data'] = json.loads(session_data['state_data'])

                    cursor.execute(messages_query, (session_id,))
                    messages = cursor.fetchall()
                    for msg in messages:
                        if msg.get('metadata') and isinstance(msg['metadata'], str):
                            msg['metadata'] = json.loads(msg['metadata'])
            finally:
                conn.close()
            return session_data, messages

        loop = asyncio.get_event_loop()
        session_data, messages = await loop.run_in_executor(None, _do_load)

        if not session_data:
            return None

        history = [
            Message(
                role=msg['role'],
                content=msg['content'],
                timestamp=msg['timestamp'],
                metadata=msg.get('metadata')
            ) for msg in messages
        ]

        session = ConversationSession(
            session_id=session_data['session_id'],
            user_id=session_data.get('user_id'),
            title=session_data.get('title', '新对话'),
            current_state=ConversationState(session_data.get('current_state', 'idle')),
            state_data=session_data.get('state_data', {}),
            history=history,
            history_summary=session_data.get('history_summary'),
            create_time=session_data.get('create_time'),
            last_active_time=session_data.get('last_active_time', datetime.now()),
            is_active=session_data.get('is_active', True),
            message_count=session_data.get('message_count', len(history))
        )

        self._cache[session_id] = session
        return session

    async def add_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        session = await self.get_session(session_id)
        if not session:
            session = await self.create_session(session_id)

        message = Message(role=role, content=content, timestamp=datetime.now(), metadata=metadata)
        session.history.append(message)
        session.last_active_time = datetime.now()
        session.message_count += 1

        if len(session.history) > self._window_size * 2 and session.message_count % self._summary_threshold == 0:
            await self._generate_summary(session)

        self._cache[session_id] = session
        # 立即持久化到数据库
        await self._persist_session(session)
        return True

    async def _generate_summary(self, session: ConversationSession):
        if len(session.history) < self._summary_threshold:
            return

        window_messages = session.history[-self._summary_threshold:]
        summary_content = f"[历史摘要 - 基于最近{len(window_messages)}条消息]\n\n"

        for msg in window_messages:
            role_name = {"user": "用户", "assistant": "助手", "system": "系统"}.get(msg.role, msg.role)
            summary_content += f"- {role_name}: {msg.content[:100]}{'...' if len(msg.content) > 100 else ''}\n"

        session.history_summary = summary_content

    async def get_context(self, session_id: str, include_summary: bool = True) -> List[Dict[str, Any]]:
        session = await self.get_session(session_id)
        if not session:
            return []

        context = []
        if include_summary and session.history_summary:
            context.append({
                "role": "system",
                "content": session.history_summary,
                "timestamp": datetime.now().isoformat()
            })

        recent_messages = session.history[-self._window_size * 2:] if len(session.history) > self._window_size * 2 else session.history

        for msg in recent_messages:
            context.append(msg.to_dict())

        return context

    async def clear_session(self, session_id: str) -> bool:
        if session_id in self._cache:
            session = self._cache[session_id]
            session.history = []
            session.history_summary = None
            session.current_state = ConversationState.IDLE
            session.state_data = {}
            session.last_active_time = datetime.now()
            session.message_count = 0

            await self._persist_session(session)
            return True
        return False

    async def update_state(self, session_id: str, state: Union[str, ConversationState], state_data: Optional[Dict[str, Any]] = None) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False

        if isinstance(state, str):
            state = ConversationState(state)

        session.current_state = state
        if state_data is not None:
            session.state_data.update(state_data)
        session.last_active_time = datetime.now()

        self._cache[session_id] = session
        return True

    async def get_session_list(self, user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if user_id:
            query = "SELECT session_id, user_id, title, current_state, create_time, last_active_time, message_count FROM conversation_session WHERE user_id = %s AND is_active = 1 ORDER BY last_active_time DESC LIMIT %s"
            params = (user_id, limit)
        else:
            query = "SELECT session_id, user_id, title, current_state, create_time, last_active_time, message_count FROM conversation_session WHERE is_active = 1 ORDER BY last_active_time DESC LIMIT %s"
            params = (limit,)

        def _do_query():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    sessions = cursor.fetchall()
                    
                    # 为每个会话获取最后一条消息作为预览
                    for session in sessions:
                        preview_query = "SELECT content, role FROM conversation_message WHERE session_id = %s ORDER BY sequence_num DESC LIMIT 1"
                        cursor.execute(preview_query, (session['session_id'],))
                        last_msg = cursor.fetchone()
                        
                        if last_msg:
                            # 截取前30个字符作为预览
                            content = last_msg['content']
                            preview = content[:30] + '...' if len(content) > 30 else content
                            session['preview'] = preview
                        else:
                            session['preview'] = '暂无消息'
                    
                    return sessions
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _do_query)
        return results

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self._cache:
            self._cache.pop(session_id)

        query = "UPDATE conversation_session SET is_active = 0 WHERE session_id = %s"

        def _do_delete():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    result = cursor.execute(query, (session_id,))
                conn.commit()
                return result
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_delete)
        return result > 0

    async def update_session_title(self, session_id: str, title: str) -> bool:
        session = await self.get_session(session_id)
        if not session:
            return False

        session.title = title
        session.last_active_time = datetime.now()
        self._cache[session_id] = session

        query = "UPDATE conversation_session SET title = %s, last_active_time = %s WHERE session_id = %s"

        def _do_update():
            conn = self._get_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, (title, datetime.now(), session_id))
                conn.commit()
            finally:
                conn.close()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_update)
        return True

conversation_manager = ConversationManager()
