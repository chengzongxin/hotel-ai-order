# 商品向量检索系统

## 目标

从 `assets/spu.xlsx` 读取商品数据，构建向量库，并根据用户描述的商品和故障现象语义检索最匹配的标准商品。匹配结果同时确定订单的服务类型（`service_order_type`）。

## 技术

- Qwen `text-embedding-v4`：生成文本向量。
- Chroma：向量存储与相似度检索（持久化到 `data/chroma_db/`）。
- BM25（`rank-bm25` + `jieba`）：商品名关键词过滤，in-memory，每次启动重建。
- `openpyxl`：读取 Excel。

## 索引文本构建

每条商品的向量索引文本：

```text
{服务商品名称} {关联故障现象}
```

- 安装、测量类商品的 `关联故障现象` 通常为空，索引文本只有商品名。
- 维修类商品索引文本包含商品名和故障现象，例如：`空调 不制冷 噪音大`。

BM25 只索引商品名（不含故障现象），用于关键词过滤。

## 检索流程

```
query（商品 + 故障）
    ↓
BM25 关键词过滤
  剔除商品名与 query 无任何关键词重叠的商品
  例："空调漏水" 时，"水柜(中修)" 名字里没有"空调" → 过滤掉
    ↓
向量检索（Chroma 余弦相似度）
  对过滤后的候选按语义相似度排名
    ↓
has_fault 惩罚（当用户描述了故障时）
  无故障描述的商品（安装/测量类）扣 0.15 分
  确保维修商品优先于同名的安装商品
  例："水龙头漏水" → "淋浴龙头/花洒(安装)" 扣分后低于 "台盆龙头(小修)"
    ↓
best_match.service_order_type → 本次订单 service_type
```

### 检索参数

| 参数 | 说明 |
|------|------|
| `query` | `product + fault`，安装场景无 fault 时追加"安装"关键词 |
| `top_k` | 返回候选数，默认 3 |
| `threshold` | 相似度阈值，低于此分数的结果被过滤 |
| `has_fault` | 是否包含故障描述，True 时对无故障商品惩罚 |

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

BM25 不持久化，每次启动从 Excel 数据重建（约 <1s）。

## 配置

`.env` 中可配置：

```env
SPU_EXCEL_PATH=assets/spu.xlsx
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_API_KEY=
PRODUCT_SEARCH_THRESHOLD=0.3
```

## Tool

### search_product

根据用户输入匹配可下单商品。

输入：

```json
{
  "query": "马桶 堵塞",
  "top_k": 3,
  "threshold": null,
  "has_fault": true
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

`PRODUCT_SEARCH_THRESHOLD` 越高，结果越少但更精确，默认 `0.3`。

如果没有结果，可以临时降低阈值，或检查用户描述里是否包含商品名称。

## 方案演进与设计决策

### 为什么引入 BM25 过滤

**问题背景**：纯向量检索时，"空调漏水"会把"水柜(中修)"排到第一（相似度 48%），而空调商品只有 44%。

**根因**：`漏水` 在向量空间里与"水系统"商品（水柜、洗手盆）语义高度相关，`漏水` 的权重压过了 `空调` 这个设备名。

**解决方案**：BM25 对商品名建倒排索引，查询 "空调漏水" 时，名字里没有"空调"的商品 BM25 得分为 0，直接被过滤掉，只剩空调相关商品参与向量排名。

### 为什么引入 has_fault 惩罚

**问题背景**：安装类商品（如"淋浴龙头/花洒"）没有故障描述，文本短、词频高，BM25 给它排名靠前；向量得分也与维修商品接近（相差 0.001）。

**根因**：用户说"水龙头漏水"是要报修，但安装商品同样命中"龙头"关键词，BM25 和向量都无法区分。

**解决方案**：当 `has_fault=True` 时，对没有故障描述的商品扣 0.15 分，让维修商品（有故障文本）优先于同名安装商品。

### 为什么不引入 Reranker

Reranker（Cross-Encoder）是在向量宽召回后，用另一个模型对 (query, doc) 整体打分重排。

**优点**：
- 去掉所有手工规则（BM25 过滤、has_fault 惩罚），模型自己学会"漏水→找维修"
- 泛化能力强，覆盖规则没想到的新问法
- 对细粒度区分（小修/中修/大修）理解更准

**缺点**：
- 延迟增加：向量召回 top-20 后每条都要过 reranker，本地模型约 +100~300ms，API 约 +200~500ms
- 额外依赖：本地部署需要 GPU/CPU 推理资源，API 调用有额外成本和故障点
- 本项目收益有限：商品库仅 454 条、结构规整，当前问题用简单规则即可解决
- 可解释性下降：规则出错易 debug，模型打出奇怪分数难排查

**结论**：当前阶段不引入。当商品库扩展到数千条、或出现大量规则覆盖不了的长尾 query 时，再评估引入 Reranker。
