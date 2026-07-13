import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import jieba
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from rank_bm25 import BM25Okapi

from config.settings import settings
from rag.qwen_embedding import QwenEmbeddingClient
from rag.spu_loader import SpuExcelLoader

PROJECT_ROOT = Path(__file__).parent.parent
PERSIST_DIR = str(PROJECT_ROOT / "data/chroma_db")
METADATA_FILE = str(PROJECT_ROOT / "data/chroma_db/build_metadata.json")
INDEX_TEXT_VERSION = "product-name-fault-v2"

VECTOR_SCORE_WEIGHT = 0.65
BM25_SCORE_WEIGHT = 0.35


def _tokenize_for_bm25(text: str) -> list[str]:
    """BM25 分词：jieba 搜索模式，过滤空 token。"""
    tokens: list[str] = []
    for token in jieba.cut_for_search(text):
        token = token.strip()
        if token:
            tokens.append(token)
    return tokens


def _normalize_score_map(scores: dict[str, float]) -> dict[str, float]:
    """将分数字典按最大值归一化到 0-1。"""
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score <= 0:
        return {key: 0.0 for key in scores}
    return {key: value / max_score for key, value in scores.items()}


def _compute_hybrid_score(vector_score: float, bm25_score: float) -> float:
    return VECTOR_SCORE_WEIGHT * vector_score + BM25_SCORE_WEIGHT * bm25_score


def _product_code(doc: Document) -> str:
    return str(doc.metadata.get("service_product_code") or "")


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
        self._documents: list[Document] = []
        self._bm25: BM25Okapi | None = None
        self.load_products()

    def get_retriever(self, k: int = 5):
        return self.vector_store.as_retriever(search_kwargs={"k": k})

    def _build_bm25_index(self) -> None:
        """基于商品名构建内存 BM25 索引，每次 load_products 时重建。"""
        corpus = [
            _tokenize_for_bm25(str(doc.metadata.get("service_product_name") or ""))
            for doc in self._documents
        ]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def _bm25_recall(
        self,
        query_tokens: list[str],
        fetch_k: int,
        service_type: str | None = None,
    ) -> list[tuple[int, float]]:
        if not self._bm25 or not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
        results: list[tuple[int, float]] = []
        for index in ranked:
            if service_type and self._documents[index].metadata.get("service_order_type") != service_type:
                continue
            score = float(scores[index])
            if score > 0:
                results.append((index, score))
            if len(results) >= fetch_k:
                break
        return results

    def _merge_hybrid_candidates(
        self,
        *,
        vector_results: list[tuple[Document, float]],
        bm25_results: list[tuple[int, float]],
    ) -> dict[str, dict[str, object]]:
        """按 service_product_code 合并向量与 BM25 候选。"""
        candidates: dict[str, dict[str, object]] = {}

        for doc, vector_score in vector_results:
            code = _product_code(doc)
            if not code:
                continue
            entry = candidates.setdefault(
                code,
                {"doc": doc, "vector_score": 0.0, "bm25_score": 0.0},
            )
            entry["vector_score"] = max(float(entry["vector_score"]), float(vector_score))

        for index, bm25_score in bm25_results:
            if index >= len(self._documents):
                continue
            doc = self._documents[index]
            code = _product_code(doc)
            if not code:
                continue
            entry = candidates.setdefault(
                code,
                {"doc": doc, "vector_score": 0.0, "bm25_score": 0.0},
            )
            entry["bm25_score"] = max(float(entry["bm25_score"]), float(bm25_score))

        return candidates

    def search(
        self,
        query: str,
        top_k: int = 5,
        threshold: float | None = None,
        service_type: str | None = None,
    ) -> list[dict]:
        """混合检索：服务类型过滤 + BM25 召回 + 向量召回 + 分数融合。"""
        query = query.strip()
        if not query:
            return []
        min_score = threshold if threshold is not None else settings.product_search_threshold
        fetch_k = top_k * 4
        query_tokens = _tokenize_for_bm25(query)

        vector_filter = {"service_order_type": service_type} if service_type else None
        vector_results = self.vector_store.similarity_search_with_relevance_scores(
            query,
            k=fetch_k,
            filter=vector_filter,
        )
        bm25_results = self._bm25_recall(query_tokens, fetch_k, service_type)
        candidates = self._merge_hybrid_candidates(
            vector_results=vector_results,
            bm25_results=bm25_results,
        )
        if not candidates:
            return []

        bm25_norm = _normalize_score_map(
            {code: float(entry["bm25_score"]) for code, entry in candidates.items()}
        )

        scored: list[tuple[float, Document]] = []
        for code, entry in candidates.items():
            doc = entry["doc"]
            assert isinstance(doc, Document)
            vector_score = float(entry["vector_score"])
            bm25_score = bm25_norm.get(code, 0.0)
            final_score = _compute_hybrid_score(vector_score, bm25_score)
            scored.append((final_score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)

        output: list[dict] = []
        for final_score, doc in scored[:top_k]:
            if final_score < min_score:
                continue
            output.append({"score": round(final_score, 4), **doc.metadata})
        return output

    def build_product_index_text(self, record) -> str:
        """向量索引文本：商品名 + 故障现象（安装/测量类只用商品名）。"""
        parts = [record.service_product_name]
        if record.fault_phenomenon:
            parts.append(record.fault_phenomenon)
        return " ".join(parts)

    def load_products(self):
        """
        从 Excel 加载商品数据，构建向量库与 BM25 索引。
        Chroma 向量库仅在 Excel 或版本变化时重建；BM25 每次启动重建。
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
        self._build_bm25_index()

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


@lru_cache
def get_product_store() -> ProductVectorStore:
    return ProductVectorStore()


if __name__ == "__main__":
    store = ProductVectorStore()
    test_cases = [
        "空调 漏水",
        "水龙头 漏水",
        "浴室门 推不动",
        "热水器 不出热水",
        "洗衣机",
    ]
    for query in test_cases:
        print(f"\n{'='*55}")
        print(f"查询：{query}")
        print("=" * 55)
        results = store.search(query, top_k=5)
        for i, r in enumerate(results, 1):
            fault_text = r["fault_phenomenon"][:28] if r["fault_phenomenon"] else "—"
            print(f"{i}. [{r['score']:.3f}] [{r['service_order_type']:8s}] {r['service_product_name']:25s}  故障={fault_text}")
