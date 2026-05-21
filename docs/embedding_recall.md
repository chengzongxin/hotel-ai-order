# 服务商品 Embedding 召回系统

## 目标

该模块从 `assets/spu.xlsx` 读取服务商品数据，并使用 Qwen text-embedding 做语义召回。

召回目标不是简单商品名，而是最终下单需要的标准服务商品参数：

- `服务商品编码`
- `服务商品名称`
- `所属服务类型`
- 归一后的 `service_order_type`，例如 `单次维修服务`、`单次安装`、`单次测量`、`托管维修`
- 关联品类、区域、故障现象等辅助字段

## 技术

- Qwen `text-embedding-v4`：生成文本向量。
- `numpy`：计算 cosine similarity。
- `openpyxl`：读取 Excel。
- 本地 `.npy` 缓存：避免每次启动重复生成向量。

## 检索字段

每条服务商品只生成两组 embedding 文本：

- `name_text`：只使用 `服务商品名称`。
- `fault_text`：只使用 `关联故障现象`。

检索时融合两类分数：

```text
final_score = name_score * 0.55 + fault_score * 0.45
```

服务类型不会参与向量文本，只作为输出字段保留。若用户表达了“安装”“测量”“维修”“托管”，系统仍会用规则给匹配的服务类型做轻量加权。

## 配置

`.env` 中可配置：

```env
SPU_EXCEL_PATH=assets/spu.xlsx
EMBEDDING_CACHE_DIR=data/embedding_cache
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_API_KEY=
SERVICE_PRODUCT_RECALL_THRESHOLD=0.55
SERVICE_PRODUCT_NAME_WEIGHT=0.55
SERVICE_PRODUCT_FAULT_WEIGHT=0.45
SERVICE_TYPE_MATCH_BONUS=0.08
SERVICE_TYPE_MISMATCH_PENALTY=0.05
```

## Tool

### recall_service_product_tool

根据用户输入召回可下单服务商品。

输入：

```json
{
  "query": "888房马桶堵了",
  "product": "马桶",
  "fault": "堵塞",
  "area": "卫生间",
  "service_type_hint": "单次维修服务",
  "top_k": 5,
  "threshold": 0.55
}
```

输出：

```json
{
  "status": "success",
  "error_code": null,
  "message": "ok",
  "data": {
    "query": "888房马桶堵了",
    "service_type_hint": "单次维修服务",
    "count": 1,
    "best_match": {
      "score": 0.8231,
      "service_product_code": "FWSP00001",
      "service_product_name": "马桶疏通",
      "service_order_type": "单次维修服务",
      "raw_service_type": "维修",
      "related_category": "马桶",
      "related_area": "卫生间",
      "fault_phenomenon": "堵塞"
    },
    "candidates": []
  },
  "fallback": null
}
```

## 阈值过滤

`threshold` 越高，结果越少但更精确。

如果没有结果，可以临时降低 `SERVICE_PRODUCT_RECALL_THRESHOLD`，或者检查用户描述里是否缺少商品、故障或区域。

## 缓存

首次调用会请求 Qwen embedding 并生成向量，速度较慢。系统会把向量缓存到：

```text
data/embedding_cache/
```

当 Excel 文件大小、修改时间、模型名称或文本构建版本变化时，会自动重建缓存。
