# 客户端会话与工作流状态契约

所有聊天、历史和确定性订单命令统一返回 `conversation_messages`。前端只消费这条
客户端消息时间线，不读取 LangChain `messages`，也不维护独立的全局订单快照。

```json
{
  "session_id": "b28b7450-5a7a-4568-a137-9e84f64039e3",
  "conversation_messages": [
    {
      "id": "24d4e55f-d4aa-4ec7-b786-b0bf4dd401a8",
      "role": "human",
      "content": "1208空调不制冷",
      "order_preview": null
    },
    {
      "id": "ee0490a5-e6ce-44cf-b2c5-f105d1818872",
      "role": "ai",
      "content": "为您推荐以下服务商品，请选择。",
      "order_preview": {
        "schema_version": 1,
        "phase": "product_selection",
        "order_info": {
          "room_number": "1208",
          "product": "空调",
          "fault": "不制冷"
        },
        "products": {
          "status": "success",
          "selected_code": null,
          "selection_rejected": false,
          "items": []
        },
        "form": {"fields": []},
        "validation": {"ready": false, "missing_fields": []},
        "capabilities": {
          "select_product": true,
          "reject_products": true,
          "update_order": false,
          "confirm_order": false,
          "cancel_order": true,
          "retry_submission": false
        },
        "coverage": {"checked": false, "covered": null},
        "submission": {"state": "not_attempted", "missing_fields": []},
        "submitted_order": null
      }
    }
  ]
}
```

## 两类消息的边界

后端同时维护两套用途不同的消息：

- `AgentState.messages`：LangChain 的 Human/AI/System/Tool 消息，只供 LLM 上下文使用；
- `AgentState.conversation_messages`：只包含前端可见的 human/ai 消息和安全状态快照。

`conversation_messages[].order_preview` 来自 `AgentState` 的客户端安全投影，不会包含
登录信息、真实接口原始请求/响应、重试计数、内部事件或工具结果。

## ConversationMessage

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定消息 ID；前端使用它追加或更新消息 |
| `role` | `human` 或 `ai` |
| `content` | 面向用户的消息正文 |
| `order_preview` | 该轮完成后的订单状态；human 消息固定为 `null` |

普通对话、选择商品、拒绝商品、确认和取消返回本次新增的消息。表单字段编辑不新增
聊天气泡，而是返回相同 `id` 的活动 AI 消息，前端按 ID upsert。

History 接口返回完整 `conversation_messages`，不再返回顶层 `order_preview` 或
`conversation_summary`。

## OrderPreview

`order_preview` 表示某条 AI 回复完成时的业务状态快照，不指定 Vue 组件或页面布局。

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 对外契约版本，当前为 `1` |
| `phase` | `idle` / `collecting` / `product_selection` / `pre_order` / `submitted` / `cancelled` |
| `service_type` | 商品确定的原始服务类型 |
| `service_type_display` | 原始服务类型展示文案 |
| `effective_service_type` | 维保校验后最终用于提交的服务类型 |
| `effective_service_type_display` | 最终服务类型展示文案 |
| `order_info` | 可安全展示的订单事实 |
| `products` | 商品候选与选择状态 |
| `form` | 后端给出的业务字段，前端决定具体控件 |
| `validation` | 完整性校验和缺失字段 |
| `capabilities` | 当前允许执行的确定性命令 |
| `coverage` | 维保范围校验摘要 |
| `submission` | 下单状态和客户端安全失败信息 |
| `submitted_order` | 成功提交后的订单快照 |

后端负责业务阶段、数据、校验和权限；前端负责把 `phase` 映射为商品选择、预下单、
成功或取消组件。历史消息中的快照只读，只有最后一条带 `order_preview` 的 AI 消息
可以根据 `capabilities` 发起操作，后端收到命令后仍会再次校验。

## 确定性命令

| 操作 | 接口 | capability |
| --- | --- | --- |
| 选择商品 | `POST /api/chat/{session_id}/select-product` | `select_product` |
| 拒绝全部候选 | `POST /api/chat/{session_id}/reject-products` | `reject_products` |
| 修改字段 | `PATCH /api/chat/{session_id}/order-info` | `update_order` |
| 确认下单 | `POST /api/chat/{session_id}/confirm` | `confirm_order` |
| 取消订单 | `POST /api/chat/{session_id}/cancel` | `cancel_order` |

## 流式事件

`POST /api/chat/stream` 返回 NDJSON：

| `type` | 用途 |
| --- | --- |
| `status` | 当前处理进度 |
| `tool_call` | 已脱敏的工具调用状态 |
| `token` | AI 回复文本片段，仅用于实时展示 |
| `final` | 本轮最终 `conversation_messages` |
| `error` | 本轮错误 |

前端可以先创建临时 human/ai 消息接收 token，收到 `final` 后用服务端返回的稳定消息
替换临时消息。

## 字段说明来源

公开字段名称、类型、枚举、说明和示例统一定义在 Pydantic 模型并生成到 OpenAPI：

- Swagger UI：`/docs`
- ReDoc：`/redoc`
- OpenAPI JSON：`/openapi.json`

Pydantic/OpenAPI 是字段级契约的唯一事实来源，本文档只解释职责和使用方式。
