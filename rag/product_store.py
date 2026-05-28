import json
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from config.settings import settings
from rag.qwen_embedding import QwenEmbeddingClient
from rag.spu_loader import SpuExcelLoader

PROJECT_ROOT = Path(__file__).parent.parent
PERSIST_DIR = str(PROJECT_ROOT / "data/chroma_db")
METADATA_FILE = str(PROJECT_ROOT / "data/chroma_db/build_metadata.json")
INDEX_TEXT_VERSION = "product-name-fault-v2"


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
        self.load_products()

    def get_retriever(self, k: int = 5):
        return self.vector_store.as_retriever(search_kwargs={"k": k})

    def search(self, query: str, top_k: int = 5, threshold: float | None = None) -> list[dict]:
        query = query.strip()
        if not query:
            return []
        min_score = threshold if threshold is not None else settings.product_match_threshold
        results = self.vector_store.similarity_search_with_relevance_scores(query, k=top_k)
        output = []
        for doc, score in results:
            if score < min_score:
                continue
            output.append({"score": round(float(score), 4), **doc.metadata})
        return output

    def build_product_index_text(self, record) -> str:
        """商品名 + 故障现象作为向量索引文本。安装/测量类商品无故障现象，只用商品名。"""
        parts = [record.service_product_name]
        if record.fault_phenomenon:
            parts.append(record.fault_phenomenon)
        return " ".join(parts)

    def load_products(self):
        """
        从 Excel 加载商品数据，构建向量库。
        Excel 文件未发生变化时跳过重建。
        """
        excel_path = PROJECT_ROOT / settings.spu_excel_path
        current_meta = {
            "excel_mtime": excel_path.stat().st_mtime,
            "excel_size": excel_path.stat().st_size,
            "embedding_model": settings.qwen_embedding_model,
            "index_text_version": INDEX_TEXT_VERSION,
        }

        metadata_path = Path(METADATA_FILE)
        if metadata_path.exists():
            saved_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            if saved_meta == current_meta:
                print("[商品向量库] 数据未变化，跳过重建")
                return

        records = SpuExcelLoader(excel_path).load()
        documents = [
            Document(
                page_content=self.build_product_index_text(r),
                metadata=asdict(r),
            )
            for r in records
        ]

        self.vector_store.reset_collection()
        self.vector_store.add_documents(documents)

        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(current_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[商品向量库] 构建完成，共 {len(documents)} 件商品")

    def _join_text(self, values: list[str]) -> str:
        return " ".join(value.strip() for value in values if value and value.strip())


@lru_cache
def get_product_store() -> ProductVectorStore:
    return ProductVectorStore()


if __name__ == "__main__":
    store = ProductVectorStore()
    results = store.search("门锁打不开")
    for r in results:
        print(r["service_product_name"], r["score"])
        print("-" * 20)
