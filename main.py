from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
import json
import time
from typing import Optional, List, Dict
from src.agents.travel_agent import TravelAgent
from src.agents.decision_agent import DecisionAgent
from src.utils.conversation_manager import conversation_manager
from src.utils.auth_manager import auth_manager
from src.utils.log_manager import log_manager
from src.services.rag_service import rag_service
from src.middleware.logging_middleware import LoggingMiddleware
from src.utils.logger import logger, set_request_id, log_performance
from src.graphs.travel_graph import travel_graph
import whisper
import os
import tempfile
from opencc import OpenCC

app = FastAPI(title="旅游向导API")

# 全链路追踪中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = set_request_id(request.headers.get("X-Request-ID"))
    start_time = time.perf_counter()
    
    logger.info(f"收到请求: {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    duration = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"请求处理完成: {request.method} {request.url.path} - 状态码: {response.status_code} - 耗时: {duration:.2f}ms",
        extra={"duration": duration}
    )
    response.headers["X-Request-ID"] = request_id
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 日志中间件 - 记录所有请求到数据库
app.add_middleware(LoggingMiddleware)

# 静态文件服务 - 提供前端页面
app.mount("/FE", StaticFiles(directory="FE"), name="FE")

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class SessionRequest(BaseModel):
    session_id: str
    title: Optional[str] = "新对话"
    preview: Optional[str] = "想去哪里旅行？"

travel_agent: Optional[TravelAgent] = None
decision_agent: Optional[DecisionAgent] = None
whisper_model: Optional[whisper.Whisper] = None

@app.on_event("startup")
async def startup_event():
    global travel_agent, decision_agent, whisper_model
    print("正在初始化旅游向导...")

    travel_agent = TravelAgent(name="TravelAssistant")
    decision_agent = DecisionAgent(name="DecisionMaker", travel_agent=travel_agent)
    print("旅游向导及决策系统初始化完成！")

    # 初始化认证管理器
    print("正在初始化认证管理器...")
    await auth_manager.initialize()
    print("认证管理器初始化完成！")

    # 初始化日志管理器
    print("正在初始化日志管理器...")
    await log_manager.initialize()
    print("日志管理器初始化完成！")

    # 初始化 RAG 服务
    print("正在初始化 RAG 服务...")
    rag_service.initialize()
    knowledge_base_path = "d:/good-project/myagent1/旅游基础知识库.txt"
    rag_service.vectorize_file(knowledge_base_path, chunk_size=256, chunk_overlap=25)
    print("RAG 服务初始化并向量化完成！")

    # 初始化会话管理器
    print("正在初始化会话管理器...")
    await conversation_manager.initialize()
    print("会话管理器初始化完成！")

    print("正在加载Whisper语音识别模型...")
    whisper_model = whisper.load_model("base")
    print("Whisper模型加载完成！")

@app.get("/")
async def root():
    return {"message": "旅游向导API服务正在运行"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

async def generate_response_stream(message: str, session_id: str):
    try:
        # 1. 获取会话上下文（包含历史消息和摘要）
        context = await conversation_manager.get_context(session_id, include_summary=True)

        # 2. 构建消息历史用于模型调用
        msg_history = []
        for msg in context:
            msg_history.append({
                'role': msg['role'],
                'content': msg['content']
            })

        # 3. 使用 LangGraph 处理用户请求
        response = await travel_graph.arun(message, msg_history)
        full_content = response

        # 4. 添加消息到会话历史
        await conversation_manager.add_message(session_id, "user", message)
        await conversation_manager.add_message(session_id, "assistant", full_content)

        # 5. 更新会话标题（如果这是第一条消息）
        session = await conversation_manager.get_session(session_id)
        if session and session.message_count == 2:
            title = message[:20] + "..." if len(message) > 20 else message
            await conversation_manager.update_session_title(session_id, title)

        # 6. 模拟流式输出
        chars_per_chunk = 2
        for i in range(0, len(full_content), chars_per_chunk):
            chunk = full_content[i : i + chars_per_chunk]
            yield f"data: {json.dumps({'event': 'message', 'data': {'content': chunk}}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.1)

        yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"data: {json.dumps({'event': 'error', 'data': {'content': str(e)}}, ensure_ascii=False)}\n\n"

@app.post("/chat/stream")
@log_performance
async def chat_stream(request: ChatRequest):
    if not travel_agent or not decision_agent:
        raise HTTPException(status_code=503, detail="服务未初始化")
    
    # 确保 session_id 存在
    if not request.session_id:
        request.session_id = f"session_{int(asyncio.get_event_loop().time() * 1000)}"
        
    return StreamingResponse(
        generate_response_stream(request.message, request.session_id),
        media_type="text/event-stream"
    )

@app.post("/chat")
@log_performance
async def chat(request: ChatRequest):
    if not travel_agent or not decision_agent:
        raise HTTPException(status_code=503, detail="服务未初始化")

    try:
        session_id = request.session_id
        if not session_id:
            session_id = f"session_{int(asyncio.get_event_loop().time() * 1000)}"

        # 1. 获取会话上下文
        context = await conversation_manager.get_context(session_id, include_summary=True)

        # 2. 构建消息历史
        msg_history = []
        for msg in context:
            msg_history.append({
                'role': msg['role'],
                'content': msg['content']
            })

        # 3. 使用 LangGraph 处理用户请求
        response = await travel_graph.arun(request.message, msg_history)
        full_content = response

        # 4. 添加消息到会话历史
        await conversation_manager.add_message(session_id, "user", request.message)
        await conversation_manager.add_message(session_id, "assistant", full_content)

        # 5. 更新会话标题
        session = await conversation_manager.get_session(session_id)
        if session and session.message_count == 2:
            title = request.message[:20] + "..." if len(request.message) > 20 else request.message
            await conversation_manager.update_session_title(session_id, title)

        return {
            "response": full_content,
            "session_id": session_id
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sessions")
async def get_sessions():
    """获取所有会话列表"""
    sessions = await conversation_manager.get_session_list(limit=100)
    return [
        {
            "id": s['session_id'],
            "title": s['title'],
            "preview": s.get('preview', '暂无消息'),
            "updated_at": s['last_active_time'].isoformat() if hasattr(s['last_active_time'], 'isoformat') else s['last_active_time']
        } for s in sessions
    ]

@app.post("/sessions")
async def create_session(request: SessionRequest):
    """创建新会话"""
    session = await conversation_manager.create_session(
        session_id=request.session_id,
        title=request.title
    )
    return {
        "session_id": session.session_id,
        "title": session.title,
        "create_time": session.create_time.isoformat()
    }

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    success = await conversation_manager.delete_session(session_id)
    if success:
        return {"message": "会话删除成功"}
    raise HTTPException(status_code=404, detail="会话不存在")

@app.post("/speech-to-text")
async def speech_to_text(file: UploadFile = File(...)):
    """语音转文字"""
    if not whisper_model:
        raise HTTPException(status_code=503, detail="Whisper模型未初始化")
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            result = whisper_model.transcribe(temp_file_path, language="zh")
            text = result["text"].strip()
            
            # 转换为简体中文
            cc = OpenCC('t2s')
            simplified_text = cc.convert(text)
            
            return {
                "success": True,
                "text": simplified_text
            }
        finally:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")

# ============ 认证相关 API ============

class RegisterRequest(BaseModel):
    user_id: str
    password: str
    username: Optional[str] = None

class LoginRequest(BaseModel):
    user_id: str
    password: str

@app.post("/auth/register")
async def register(request: RegisterRequest, http_request: Request):
    """用户注册"""
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent", "")[:500]

    result = await auth_manager.register(
        user_id=request.user_id,
        password=request.password,
        username=request.username,
        role='user'
    )

    if result["success"]:
        await log_manager.log(
            action="USER_REGISTER",
            user_id=request.user_id,
            username=request.username or request.user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            response_status=200
        )

    return result

@app.post("/auth/login")
async def login(request: LoginRequest, http_request: Request):
    """用户登录"""
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent", "")[:500]

    result = await auth_manager.login(
        user_id=request.user_id,
        password=request.password,
        ip_address=ip_address,
        user_agent=user_agent
    )

    return result

@app.post("/auth/logout")
async def logout(http_request: Request):
    """用户登出"""
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent", "")[:500]

    user_id = http_request.headers.get("X-User-ID")
    if user_id:
        await auth_manager.logout(user_id, ip_address, user_agent)

    return {"success": True, "message": "登出成功"}

@app.get("/auth/userinfo")
async def get_user_info(http_request: Request):
    """获取用户信息"""
    user_id = http_request.headers.get("X-User-ID")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    user_info = await auth_manager.get_user_info(user_id)
    if not user_info:
        raise HTTPException(status_code=404, detail="用户不存在")

    return user_info

@app.get("/admin/users")
async def get_all_users(role: Optional[str] = None, limit: int = 100, offset: int = 0):
    """获取所有用户列表（管理员专用）"""
    users = await auth_manager.get_all_users(role=role, limit=limit, offset=offset)
    return users

# ============ 日志相关 API ============

class LogQueryParams(BaseModel):
    user_id: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = 100
    offset: int = 0

@app.post("/admin/logs/system")
async def get_system_logs(params: LogQueryParams):
    """获取系统日志（管理员专用）"""
    from datetime import datetime

    start_time = None
    end_time = None

    if params.start_time:
        start_time = datetime.fromisoformat(params.start_time)
    if params.end_time:
        end_time = datetime.fromisoformat(params.end_time)

    logs = await log_manager.get_logs(
        user_id=params.user_id,
        action=params.action,
        resource=params.resource,
        start_time=start_time,
        end_time=end_time,
        limit=params.limit,
        offset=params.offset
    )

    total = await log_manager.get_log_count(
        user_id=params.user_id,
        action=params.action,
        resource=params.resource,
        start_time=start_time,
        end_time=end_time
    )

    return {"logs": logs, "total": total}

@app.post("/admin/logs/login")
async def get_login_logs(params: LogQueryParams):
    """获取登录日志（管理员专用）"""
    from datetime import datetime

    start_time = None
    end_time = None

    if params.start_time:
        start_time = datetime.fromisoformat(params.start_time)
    if params.end_time:
        end_time = datetime.fromisoformat(params.end_time)

    logs = await log_manager.get_login_logs(
        user_id=params.user_id,
        login_type=params.action,
        start_time=start_time,
        end_time=end_time,
        limit=params.limit,
        offset=params.offset
    )

    return {"logs": logs}

@app.delete("/admin/logs/cleanup")
async def cleanup_old_logs(days: int = 30):
    """清理旧日志（管理员专用）"""
    deleted_count = await log_manager.delete_old_logs(days=days)
    return {"success": True, "deleted_count": deleted_count}

if __name__ == "__main__":
    import uvicorn
    from src.config.settings import config
    
    uvicorn.run(
        app,
        host=config.SERVER_HOST,
        port=config.SERVER_PORT,
        log_level=config.LOG_LEVEL.lower()
    )