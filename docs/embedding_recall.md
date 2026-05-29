# 商品向量检索系统

## 目标

从 `assets/spu.xlsx` 读取商品数据，构建向量库，并根据用户描述的商品和故障现象语义检索最匹配的标准商品。匹配结果同时确定订单的服务类型（`service_order_type`）。

## 技术

- Qwen `text-embedding-v4`：生成文本向量。
- Chroma：向量存储与相似度检索（持久化到 `data/chroma_db/`）。
- `openpyxl`：读取 Excel。

## 索引文本构建

每条商品的向量索引文本：

```text
{服务商品名称} {关联故障现象}
```

- 安装、测量类商品的 `关联故障现象` 通常为空，索引文本只有商品名。
- 维修类商品索引文本包含商品名和故障现象，例如：`空调 不制冷 噪音大`。

## 检索流程

1. 检索 query = `用户说的商品 + 故障现象`。
2. 安装/测量场景无故障现象时，query 退化为只有商品名。
3. Chroma 余弦相似度召回 Top-K，过滤低于阈值的候选。
4. `best_match.service_order_type` 作为本次订单的 `service_type`。

## 向量库生命周期

向量库构建状态记录在 `data/chroma_db/build_metadata.json`：

```json
{
  "excel_mtime": 1234567890.0,
  "excel_size": 12345,
  "embedding_model": "text-embedding-v4",
  "index_text_version": "product-name-fault-v2"
}
```

当以下任一条件变化时，启动时自动重建：

- Excel 文件的修改时间或大小
- Embedding 模型名称
- `index_text_version`（代码版本号）

## 配置

`.env` 中可配置：

```env
SPU_EXCEL_PATH=assets/spu.xlsx
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_API_KEY=
PRODUCT_MATCH_THRESHOLD=0.55
```

## Tool

### match_product_tool

根据用户输入匹配可下单商品。

输入：

```json
{
  "query": "马桶堵了",
  "product": "马桶",
  "fault": "堵塞",
  "top_k": 3,
  "threshold": null
}
```

输出：

```json
{
  "status": "success",
  "data": {
    "query": "马桶 堵塞",
    "best_match": {
      "score": 0.8231,
      "service_product_code": "FWSP00001",
      "service_product_name": "马桶疏通",
      "service_order_type": "单次维修服务",
      "fault_phenomenon": "堵塞"
    },
    "candidates": [],
    "count": 1
  }
}
```

## 阈值过滤

`PRODUCT_MATCH_THRESHOLD` 越高，结果越少但更精确，默认 `0.55`。

如果没有结果，可以临时降低阈值，或检查用户描述里是否包含商品名称。
