# LangSmith 调试指南

项目已经接入 LangSmith tracing。开启后，你可以在 LangSmith 里查看：

- Prompt
- Tool
- State
- Token
- Error

## 1. 配置 .env

在 `.env` 中配置：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=你的 LangSmith API Key
LANGSMITH_PROJECT=hotel-ai-order-agent
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

本项目会优先读取 `.env`，并把这些值同步到 `os.environ`，确保 LangChain/LangGraph 可以自动上报 trace。

## 2. 启动后端

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

发送一次请求：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"debug-1208","message":"1208房间空调不制冷，比较急"}'
```

## 3. 在 LangSmith 看什么

### Prompt

进入项目 `hotel-ai-order-agent`，打开一次 trace。

重点看：

- `intent_node`
- `extractor_node`

这些节点里会显示传给模型的 `SystemMessage` 和 `HumanMessage`。

### State

Graph run 的 metadata 里会带：

```json
{
  "session_id": "...",
  "app_env": "local",
  "message_count": 2,
  "has_conversation_summary": true
}
```

节点输入和输出里可以看到 State 的变化，例如：

- `intent`
- `service_type`
- `order_info`
- `missing_info`
- `retry_count`
- `conversation_summary`

### Token

打开具体 LLM run，可以看到：

- prompt tokens
- completion tokens
- total tokens
- latency

如果模型服务商没有完整返回 token usage，LangSmith 里可能只显示部分统计。

### Error

如果某个节点失败，LangSmith 会把错误挂在对应节点上。

常见错误：

- JSON schema 校验失败
- Qwen/OpenAI 兼容接口参数错误
- Tool 超时
- SQLite checkpoint 错误

### Tool

当前下单工作流主要是显式节点流程，RAG 和下单 Tool 已注册在 `tools/registry.py`。

当后续把 ToolNode 或工具调用接入主图后，LangSmith 会显示工具 run，例如：

- `match_product_tool`
- `search_product_tool`
- `create_order_tool`
- `check_package_tool`

## 4. Trace 筛选

本项目给每次 graph run 加了 tags：

```text
hotel-ai-order
order
local
```

你可以在 LangSmith 里按 tag 筛选下单链路。
