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

## 可读状态镜像

项目使用 `memory/readable_sqlite_saver.py::ReadableAsyncSqliteSaver` 包装
LangGraph 的 SQLite saver。初始化时会为原生 `checkpoints` 表增加一个可空字段：

```text
state_json TEXT
```

每次保存新 checkpoint 时，同一事务会同时写入：

- `checkpoint`：LangGraph 默认序列化的 msgpack BLOB，是恢复状态的唯一可信数据。
- `state_json`：`checkpoint["channel_values"]` 的可读 JSON，仅用于排查和查询。

不要根据 `state_json` 恢复或修改图状态，也不要手工更新原始 checkpoint BLOB。

普通 SQLite 工具可以直接查询可读状态：

```sql
SELECT
    thread_id,
    checkpoint_id,
    json_extract(state_json, '$.step') AS node_name,
    COALESCE(
        json_extract(state_json, '$.order.items[0].room_number'),
        json_extract(state_json, '$.product_request.room_number')
    ) AS room_number,
    state_json
FROM checkpoints
WHERE state_json IS NOT NULL
ORDER BY checkpoint_id DESC;
```

升级前已经存在的 checkpoint 行不会在应用启动时自动回填，以免大数据库启动时
长时间占用写锁和快速膨胀。停止后端写入后，可显式执行：

```bash
# 先小批验证
uv run python -m scripts.backfill_checkpoint_state_json --limit 25

# 确认磁盘空间和结果后，回填全部旧记录
uv run python -m scripts.backfill_checkpoint_state_json --batch-size 25
```

也可以对数据库副本操作：

```bash
uv run python -m scripts.backfill_checkpoint_state_json \
  --db /tmp/agent_memory.sqlite3 \
  --batch-size 25
```

完整 State 可能包含手机号、地址、联系人和下单参数。`state_json` 不做脱敏，数据库
文件和导出结果必须按敏感业务数据管理。

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

- `conversation_messages` 来自 `state["conversation_messages"]`

`DELETE /chat/{session_id}` 会删除对应 LangGraph thread 的 checkpoint。

## conversation summary

方案 B 暂时不再用本地消息表生成摘要。

当前主图没有摘要字段。如果后续长对话变多，可新增 `summary_node` 并正式定义摘要的生成、保存和消费链路。
