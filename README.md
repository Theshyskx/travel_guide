# 🌍 智能旅游向导 (Travel Guide)

基于 LangGraph 的智能旅游助手，提供专业的旅游信息检索和智能对话服务。

## ✨ 功能特性

- 🤖 **智能对话**：支持自然语言交互，理解用户旅游需求
- 🔍 **知识检索**：基于数据库和 RAG 的精准信息检索
- 🧠 **决策引擎**：智能判断何时使用知识库，何时使用大模型
- 💬 **多轮对话**：支持上下文保持的对话管理
- 🌐 **RESTful API**：提供完整的 API 接口

## 🛠️ 技术栈

- **框架**: FastAPI + LangGraph
- **LLM**: GLM-4-Flash (智谱AI)
- **向量数据库**: ChromaDB
- **关系数据库**: MySQL
- **语言**: Python 3.10+

## 📦 安装

```bash
# 克隆仓库
git clone https://github.com/Theshyskx/travel_guide.git
cd travel_guide

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

## ⚙️ 配置

1. 复制配置模板：
```bash
cp .env.example .env
```

2. 编辑 `.env` 文件，配置以下内容：
```env
# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=travel_guide

# 模型配置
OPENAI_API_KEY=your_api_key_here
OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MODEL_NAME=glm-4-flash

# 向量数据库路径
VECTOR_STORE_PATH=./chroma_db
```

3. 初始化数据库：
```bash
python init_auth_db.py
```

## 🚀 启动

```bash
# 开发模式
python main.py

# 或使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8081 --reload
```

服务启动后访问：http://localhost:8081

## 🔌 API 接口

### 会话管理

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/sessions` | 获取会话列表 |
| POST | `/sessions` | 创建新会话 |
| DELETE | `/sessions/{session_id}` | 删除会话 |

### 聊天接口

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/chat` | 发送消息 |

### 示例请求

```bash
# 创建会话
curl -X POST http://localhost:8081/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test_session", "title": "测试会话"}'

# 发送消息
curl -X POST http://localhost:8081/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "丽江古城住宿推荐", "session_id": "test_session"}'
```

## 📁 项目结构

```
travel_guide/
├── main.py                 # 主应用入口
├── .env                    # 环境配置（需自行创建）
├── .env.example            # 配置模板
├── requirements.txt        # 依赖列表
├── init_auth_db.py         # 数据库初始化
└── src/
    ├── agents/             # 智能体模块
    │   ├── travel_agent.py     # 旅游检索智能体
    │   └── decision_agent.py   # 决策智能体
    ├── graphs/             # LangGraph 工作流
    │   └── travel_graph.py     # 旅游对话图
    ├── services/           # 业务服务
    │   ├── rag_service.py      # RAG 检索服务
    │   └── hierarchical_retrieval.py
    ├── database/           # 数据库管理
    │   ├── db_manager.py       # 数据库连接
    │   └── schema/             # 数据库schema
    ├── utils/              # 工具模块
    │   ├── logger.py           # 日志管理
    │   ├── conversation_manager.py
    │   └── auth_manager.py     # 认证管理
    ├── middleware/         # 中间件
    │   └── logging_middleware.py
    └── config/             # 配置管理
        └── settings.py         # 全局配置
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License