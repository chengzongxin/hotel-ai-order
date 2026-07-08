# LangGraph Checkpoint Memory

## 设计目标

当前项目先试用“方案 B”：尽量依靠 LangGraph 最新生态管理多轮状态。

核心思路：

- `messages`、已抽取字段、缺失字段、当前步骤等运行状态，都保存在 LangGraph checkpoint 里。
- 后端不再用 `SQLiteChatMemory` 单独维护 `sessions` 表和 `messages` 表。
- PostgreSQL 日志仍然是可选审计日志，不参与 Agent 上下文恢复。

## session_id

每一次对话都属于一个 `session_id`。前端或调用方只要把同一个 `session_id` 传回来，后端就能恢复上下文。

请求示例：

```json
{
  "session_id": "guest-1208",
  "message": "空调不制冷"
}
```

## SQLite 文件

SQLite 文件仍然存在，但现在主要作为 LangGraph checkpoint 存储。默认路径：

```text
data/agent_memory.sqlite3
```

可以通过 `.env` 修改：

```env
SQLITE_MEMORY_PATH=data/agent_memory.sqlite3
```

LangGraph checkpoint 表由 `AsyncSqliteSaver` 自动创建，不建议手写 SQL 直接修改。

## 恢复上下文

恢复上下文依赖同一个 `thread_id={user_id}:{session_id}`。`session_id` 必须由前端生成并在每轮请求中传入，后端不再自动生成。

代码中对应配置：

```python
config={"configurable": {"thread_id": f"{user.user_id}:{session_id}"}}
```

每次请求只传入本轮用户消息：

```python
turn_input_state = {
    "user_id": active_user.user_id,
    "messages": [HumanMessage(content=user_message)],
    "last_user_message": user_message,
}
```

因为 `AgentState.messages` 使用了 LangGraph 的 `add_messages` reducer，所以新消息会追加到 checkpoint 里的历史消息后面，而不是覆盖整段历史。

## 历史接口

`GET /chat/{session_id}/history` 现在从 LangGraph checkpoint 读取 state：

- `messages` 来自 `state["messages"]`
- `conversation_summary` 来自 `state["conversation_summary"]`

`DELETE /chat/{session_id}` 会删除对应 LangGraph thread 的 checkpoint。

## conversation summary

方案 B 暂时不再用本地消息表生成摘要。

如果后续长对话变多，建议新增一个 `summary_node`，让摘要也成为 LangGraph state 的一部分。这样 summary 的生成、保存和调试都能继续留在图里。
