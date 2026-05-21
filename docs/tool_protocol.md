# AI 维修下单系统 Tool 协议

## 设计目标

Tool 是 Agent 调用外部能力的接口。每个 Tool 只做一件事，输入和输出都必须是 JSON，方便模型、后端服务和日志系统统一处理。

## 统一响应格式

```json
{
  "status": "success | error | fallback",
  "error_code": "INVALID_INPUT | NOT_FOUND | TIMEOUT | UPSTREAM_ERROR | FALLBACK_USED | null",
  "message": "给模型和系统看的简短说明",
  "data": {},
  "fallback": null
}
```

字段说明：

- `status`：Tool 执行状态。
- `error_code`：错误码；成功时为 `null`。
- `message`：简短说明，不放长文本。
- `data`：业务数据，必须是 JSON 对象。
- `fallback`：兜底动作；没有兜底时为 `null`。

## Tool 列表

### search_product_tool

职责：根据用户描述查询维修商品或设备。

输入：

```json
{
  "keyword": "空调",
  "area": "卧室"
}
```

输出：

```json
{
  "status": "success",
  "error_code": null,
  "message": "ok",
  "data": {
    "products": [
      {
        "product_id": "air_conditioner",
        "name": "空调",
        "areas": ["卧室", "客厅"]
      }
    ]
  },
  "fallback": null
}
```

### check_package_tool

职责：检查房间或商品是否在维修服务包内。

输入：

```json
{
  "room_number": "1208",
  "product": "空调"
}
```

输出：

```json
{
  "status": "success",
  "error_code": null,
  "message": "ok",
  "data": {
    "room_number": "1208",
    "product": "空调",
    "is_covered": true,
    "package_name": "基础客房维修包"
  },
  "fallback": null
}
```

### create_order_tool

职责：创建维修工单。

输入：

```json
{
  "room_number": "1208",
  "product": "空调",
  "fault": "不制冷",
  "area": "卧室",
  "urgency": "high"
}
```

输出：

```json
{
  "status": "success",
  "error_code": null,
  "message": "order created",
  "data": {
    "order_id": "ORDER-1234567890",
    "room_number": "1208",
    "product": "空调",
    "fault": "不制冷",
    "area": "卧室",
    "urgency": "high"
  },
  "fallback": null
}
```

## 超时策略

所有下单 Tool 默认超时时间为 3 秒。超时后不直接让 Agent 崩溃，而是返回标准 fallback JSON。

示例：

```json
{
  "status": "fallback",
  "error_code": "FALLBACK_USED",
  "message": "创建订单超时，已生成待人工处理任务",
  "data": {
    "room_number": "1208",
    "product": "空调",
    "fault": "不制冷",
    "area": "卧室",
    "urgency": "high"
  },
  "fallback": {
    "fallback_type": "manual_order",
    "next_action": "staff_create_order_manually"
  }
}
```

## 错误码

- `INVALID_INPUT`：输入字段不合法。
- `NOT_FOUND`：没有找到业务数据。
- `TIMEOUT`：Tool 执行超时。
- `UPSTREAM_ERROR`：上游系统异常。
- `FALLBACK_USED`：已启用兜底方案。
