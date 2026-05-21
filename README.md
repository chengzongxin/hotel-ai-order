# LangGraph + FastAPI AI Agent

这是一个模块化 AI Agent 项目骨架，技术栈包含 FastAPI、LangGraph、Redis、PostgreSQL，并预留 Qdrant 接入位置。

## 目录结构

```text
.
├── api/
│   ├── __init__.py
│   └── routes.py
├── app/
│   ├── __init__.py
│   └── main.py
├── config/
│   ├── __init__.py
│   ├── database.py
│   └── settings.py
├── graph/
│   ├── __init__.py
│   ├── builder.py
│   └── state.py
├── memory/
│   ├── __init__.py
│   ├── postgres_log.py
│   └── redis_memory.py
├── prompts/
│   └── system.md
├── schemas/
│   ├── __init__.py
│   └── chat.py
├── tools/
│   ├── __init__.py
│   ├── basic.py
│   ├── qdrant_placeholder.py
│   └── registry.py
├── .env
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── README.md
├── pyproject.toml
├── requirements.txt
└── uv.lock
```

## 依赖管理

项目使用 `uv` 管理 Python 依赖，核心依赖定义在 `pyproject.toml`，锁定版本在 `uv.lock`。

本地安装依赖：

```bash
uv sync
```

本地启动后端：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`requirements.txt` 只保留迁移说明，不再作为主依赖文件。

## LangGraph Studio

项目已配置 LangGraph Studio：

```bash
uv run langgraph dev
```

启动后打开终端提示的 Studio 地址，选择：

```text
order_graph
```

Studio 里输入的是 LangGraph State，不是 FastAPI 请求体。示例：

```json
{
  "conversation_id": "studio-1208",
  "messages": [
    {
      "role": "user",
      "content": "1208房间空调不制冷，比较急"
    }
  ],
  "retry_count": 0,
  "off_topic_count": 0,
  "conversation_summary": "",
  "last_user_message": "1208房间空调不制冷，比较急"
}
```

Studio 适合看节点跳转、State 变化、conditional edge 和 interrupt；LangSmith Trace 适合看 Prompt、Token、Error 和模型输入输出。

## 启动方式

1. 修改 `.env` 中的 `OPENAI_API_KEY`。
2. 启动服务：

```bash
docker compose up --build
```

3. 健康检查：

```bash
curl http://localhost:8000/health
```

4. 发起对话：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"你好，请介绍一下你自己"}'
```

5. 继续多轮对话，把上一步返回的 `session_id` 传回来：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"替换为真实ID","message":"刚才我们聊了什么？"}'
```

## 模块说明

- `graph/state.py`：定义 LangGraph 使用的 `TypedDict` State。
- `graph/builder.py`：构建 LangGraph 节点、工具循环和运行入口。
- `prompts/system.md`：文件化 Prompt，修改提示词不需要改 Python 代码。
- `tools/`：所有工具独立注册，后续新增工具只需要加入 `registry.py`。
- `memory/sqlite_memory.py`：SQLite 多轮对话记忆和 summary。
- `memory/postgres_log.py`：PostgreSQL 持久化对话日志。
- `config/settings.py`：统一读取 `.env` 配置。
- `docker-compose.yml`：同时启动 API、Redis、PostgreSQL、Qdrant。
