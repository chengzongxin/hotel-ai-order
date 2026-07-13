# 前端工作流状态契约

`/api/chat`、`/api/chat/stream`、会话历史和确定性订单命令统一返回
`order_preview`。这个名字为兼容现有接口保留；它表示的是**面向客户端的业务状态快照**，
不是 LangGraph `AgentState`，也不指定 Vue 组件或页面布局。

## 接口字段说明

公开字段的名称、类型、必填性、枚举值、说明和示例统一定义在 Pydantic 响应模型中，
并自动生成到 OpenAPI。启动服务后可直接查看：

- Swagger UI：`/docs`
- ReDoc：`/redoc`
- OpenAPI JSON：`/openapi.json`

Pydantic/OpenAPI 是字段级接口契约的唯一事实来源；本文档只解释职责边界、流程和使用方式，
避免在 Python、OpenAPI 和 Markdown 中重复维护同一份字段表。

## 职责边界

后端负责：

- 当前业务 `phase`；
- 订单、商品、表单和提交结果数据；
- `validation` 业务校验；
- `capabilities` 当前允许执行的命令。

前端负责：

- `phase` 与页面组件的映射；
- 表单控件、布局、颜色、图标和动画；
- 根据 `capabilities` 展示或禁用操作按钮。

前端不应重新推导必填规则或能否提交。后端收到命令后仍会再次校验，不能把按钮禁用当作安全边界。

## 顶层结构

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 对外契约版本，当前为 `1` |
| `phase` | `idle` / `collecting` / `product_selection` / `pre_order` / `submitted` / `cancelled` |
| `service_type` | 商品决定的原始服务类型 |
| `service_type_display` | 面向用户的原始服务类型文案 |
| `effective_service_type` | 维保校验后最终用于提交的服务类型 |
| `effective_service_type_display` | 最终服务类型文案 |
| `order_info` | 可安全展示的用户订单信息 |
| `products` | 商品候选与选中态 |
| `form` | 后端给出的业务字段描述，前端决定具体控件 |
| `validation` | 是否可以提交及缺失字段 |
| `capabilities` | 当前允许执行的确定性业务命令 |
| `coverage` | 维保范围校验摘要 |
| `submission` | 提交状态和面向客户端的失败信息 |
| `submitted_order` | 提交成功后的安全订单快照 |

## 示例

```json
{
  "schema_version": 1,
  "phase": "pre_order",
  "service_type": "托管维修",
  "service_type_display": "托管维修（客房）",
  "effective_service_type": "托管维修",
  "effective_service_type_display": "托管维修（客房）",
  "order_info": {
    "room_number": "301",
    "product": "门锁",
    "fault": "打不开",
    "area": "客房",
    "urgency": "medium"
  },
  "products": {
    "status": "success",
    "query": "门锁 打不开",
    "feedback": "已匹配到门锁维修商品。",
    "selected_code": "FWSP01537",
    "selection_rejected": false,
    "items": [
      {
        "code": "FWSP01537",
        "name": "门锁损坏（困客人）",
        "service_type": "托管维修",
        "rank": 1,
        "is_recommended": true,
        "is_selected": true
      }
    ]
  },
  "form": {
    "fields": [
      {
        "key": "expected_time",
        "label": "期望开工/完工时间",
        "value": null,
        "required": true,
        "editable": true,
        "input_type": "text",
        "options": []
      }
    ]
  },
  "validation": {
    "ready": false,
    "missing_fields": ["expected_start_time"]
  },
  "capabilities": {
    "select_product": false,
    "reject_products": false,
    "update_order": true,
    "confirm_order": false,
    "cancel_order": true,
    "retry_submission": false
  },
  "coverage": {
    "checked": true,
    "covered": true,
    "reason": "该商品在维保范围内"
  },
  "submission": {
    "state": "not_attempted",
    "order_no": null,
    "failure_code": null,
    "failure_message": null,
    "missing_fields": []
  },
  "submitted_order": null
}
```

内部的 `user_confirmed`、重试计数、事件日志、上游请求参数和原始响应不会通过该契约暴露。

## 前端渲染

推荐由前端维护组件映射：

```ts
const componentByPhase = {
  idle: ChatPanel,
  collecting: ChatPanel,
  product_selection: ProductSelectionCard,
  pre_order: OrderPreviewCard,
  submitted: OrderSuccessCard,
  cancelled: CancelledNotice,
}
```

`input_type` 是字段编辑提示，不是组件名称。前端可以把 `select` 渲染成下拉框或单选组，后端不感知。

## 确定性命令

UI 中已经明确的行为不再交给 LLM 二次识别：

| 操作 | 接口 | 对应 capability |
| --- | --- | --- |
| 选择商品 | `POST /api/chat/{session_id}/select-product` | `select_product` |
| 拒绝全部候选 | `POST /api/chat/{session_id}/reject-products` | `reject_products` |
| 修改字段 | `PATCH /api/chat/{session_id}/order-info` | `update_order` |
| 确认下单 | `POST /api/chat/{session_id}/confirm` | `confirm_order` |
| 取消订单 | `POST /api/chat/{session_id}/cancel` | `cancel_order` |

每个命令完成后都返回最新 `order_preview`，前端直接替换本地快照。

## 流式事件

`POST /api/chat/stream` 返回 NDJSON：

| `type` | 用途 |
| --- | --- |
| `status` | 当前处理进度 |
| `preview` | 增量工作流快照 |
| `tool_call` | 已脱敏的工具调用状态 |
| `token` | AI 回复文本片段 |
| `final` | 最终回复和最终工作流快照 |
| `error` | 本轮错误 |

`preview` 和 `final` 中的 `order_preview` 使用相同结构。
