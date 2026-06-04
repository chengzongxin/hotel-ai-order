import json
import warnings
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import jieba
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from config.settings import settings
from rag.qwen_embedding import QwenEmbeddingClient
from rag.spu_loader import SpuExcelLoader

PROJECT_ROOT = Path(__file__).parent.parent
PERSIST_DIR = str(PROJECT_ROOT / "data/chroma_db")
METADATA_FILE = str(PROJECT_ROOT / "data/chroma_db/build_metadata.json")
INDEX_TEXT_VERSION = "product-name-fault-v2"

# 有故障词时对"无故障描述"商品（安装/测量类）的分数惩罚值
NO_FAULT_PENALTY = 0.15
# BM25 过滤池大小：足够大以覆盖所有有关键词重叠的商品
BM25_FILTER_K = 80


def _jieba_tokenize(text: str) -> list[str]:
    """jieba 搜索模式分词，过滤空字符串。"""
    return [token for token in jieba.cut_for_search(text) if token.strip()]


class QwenEmbeddings(Embeddings):
    """将 QwenEmbeddingClient 包装为 LangChain Embeddings 接口。"""

    def __init__(self):
        self._client = QwenEmbeddingClient()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_texts(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_texts([text])[0].tolist()


class ProductVectorStore:
    def __init__(self):
        self.embed_model = QwenEmbeddings()
        self.vector_store = Chroma(
            collection_name="products",
            embedding_function=self.embed_model,
            persist_directory=PERSIST_DIR,
        )
        self._bm25_retriever: BM25Retriever | None = None
        self._documents: list[Document] = []
        self.load_products()

    def get_retriever(self, k: int = 5):
        return self.vector_store.as_retriever(search_kwargs={"k": k})

    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float | None = None,
        has_fault: bool = False,
    ) -> list[dict]:
        """
        混合检索：BM25 过滤 + 向量排名 + 故障惩罚。

        has_fault: 当为 True 时，对没有故障描述的商品（安装/测量类）扣减分数，
                   确保用户描述了故障时优先匹配维修商品。
        """
        query = query.strip()
        if not query:
            return []
        min_score = threshold if threshold is not None else settings.product_search_threshold
        fetch_k = top_k * 4

        # ── BM25 过滤：剔除与查询词无任何关键词重叠的商品 ──────────────────────
        # 原理：BM25 对零分（无词命中）的商品不返回，利用这一特性做过滤而非排名
        bm25_filter_codes: set[str] = set()
        if self._bm25_retriever is not None:
            self._bm25_retriever.k = BM25_FILTER_K
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bm25_docs = self._bm25_retriever.invoke(query)
            bm25_filter_codes = {
                doc.metadata.get("service_product_code", "")
                for doc in bm25_docs
                if doc.metadata.get("service_product_code")
            }

        # ── 向量检索（语义排名）──────────────────────────────────────────────
        vector_results = self.vector_store.similarity_search_with_relevance_scores(query, k=fetch_k)

        # ── 过滤 + 故障惩罚 + 排序 ──────────────────────────────────────────
        scored: list[tuple[float, Document]] = []
        for doc, v_score in vector_results:
            code = doc.metadata.get("service_product_code", "")
            # BM25 过滤：跳过与查询无任何关键词重叠的商品（过滤池非空时生效）
            if bm25_filter_codes and code not in bm25_filter_codes:
                continue
            # 故障惩罚：有故障描述时，对无故障文本的商品（安装/测量类）降权
            adjusted = float(v_score)
            if has_fault and not doc.metadata.get("fault_phenomenon"):
                adjusted -= NO_FAULT_PENALTY
            scored.append((adjusted, doc))

        # 分数不足时回退到纯向量结果（避免过滤过严导致空返回）
        if len(scored) < top_k:
            scored = [(float(s), d) for d, s in vector_results]

        scored.sort(key=lambda x: x[0], reverse=True)

        output = []
        for adjusted_score, doc in scored[:top_k]:
            if adjusted_score < min_score:
                continue
            output.append({"score": round(adjusted_score, 4), **doc.metadata})

        return output

    def build_product_index_text(self, record) -> str:
        """向量索引文本：商品名 + 故障现象（安装/测量类只用商品名）。"""
        parts = [record.service_product_name]
        if record.fault_phenomenon:
            parts.append(record.fault_phenomenon)
        return " ".join(parts)

    def load_products(self):
        """
        从 Excel 加载商品数据，构建向量库和 BM25 索引。
        - BM25 每次启动都重建（内存中）。
        - Chroma 向量库仅在 Excel 或版本变化时重建。
        """
        excel_path = PROJECT_ROOT / settings.spu_excel_path
        current_meta = {
            "excel_mtime": excel_path.stat().st_mtime,
            "excel_size": excel_path.stat().st_size,
            "embedding_model": settings.qwen_embedding_model,
            "index_text_version": INDEX_TEXT_VERSION,
        }

        records = SpuExcelLoader(excel_path).load()
        self._documents = [
            Document(
                page_content=self.build_product_index_text(r),
                metadata=asdict(r),
            )
            for r in records
        ]
        self._build_bm25(self._documents)

        metadata_path = Path(METADATA_FILE)
        if metadata_path.exists():
            saved_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            if saved_meta == current_meta:
                print(f"[商品向量库] 数据未变化，跳过重建（共 {len(self._documents)} 件商品）")
                return

        self.vector_store.reset_collection()
        self.vector_store.add_documents(self._documents)

        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(current_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[商品向量库] 构建完成，共 {len(self._documents)} 件商品")

    def _build_bm25(self, documents: list[Document]) -> None:
        """BM25 只索引商品名，用于关键词过滤（去除无词重叠的无关商品）。"""
        name_docs = [
            Document(
                page_content=doc.metadata.get("service_product_name", ""),
                metadata=doc.metadata,
            )
            for doc in documents
        ]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._bm25_retriever = BM25Retriever.from_documents(
                name_docs,
                preprocess_func=_jieba_tokenize,
                k=BM25_FILTER_K,
            )
        print(f"[BM25 索引] 构建完成，共 {len(name_docs)} 件商品")

    def _join_text(self, values: list[str]) -> str:
        return " ".join(value.strip() for value in values if value and value.strip())


@lru_cache
def get_product_store() -> ProductVectorStore:
    return ProductVectorStore()


if __name__ == "__main__":
    store = ProductVectorStore()
    test_cases = [
        ("空调 漏水", True),
        ("水龙头 漏水", True),
        ("浴室门 推不动", True),
        ("热水器 不出热水", True),
        ("洗衣机", False),
    ]
    for query, has_fault in test_cases:
        print(f"\n{'='*55}")
        print(f"查询：{query}  (has_fault={has_fault})")
        print("=" * 55)
        results = store.search(query, top_k=5, has_fault=has_fault)
        for i, r in enumerate(results, 1):
            fault_text = r["fault_phenomenon"][:28] if r["fault_phenomenon"] else "—"
            print(f"{i}. [{r['score']:.3f}] [{r['service_order_type']:8s}] {r['service_product_name']:25s}  故障={fault_text}")
