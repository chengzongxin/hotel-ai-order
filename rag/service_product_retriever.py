import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from config.settings import settings
from rag.qwen_embedding import QwenEmbeddingClient
from rag.spu_loader import ServiceProductRecord, SpuExcelLoader

EMBEDDING_KINDS = ("name", "fault")

SERVICE_TYPE_KEYWORDS: dict[str, list[str]] = {
    "托管维修": ["托管", "维保", "长期维护", "代管"],
    "单次安装": ["安装", "装一下", "帮我装", "拆装", "换装"],
    "单次测量": ["测量", "量尺寸", "量一下", "量尺", "量房", "上门量"],
    "单次维修服务": ["维修", "报修", "坏了", "堵了", "漏水", "不亮", "不制冷", "打不开", "故障"],
}


@dataclass(frozen=True)
class ServiceProductRecallResult:
    final_score: float
    name_score: float
    fault_score: float
    service_type_adjustment: float
    record: ServiceProductRecord

    def to_dict(self) -> dict[str, Any]:
        payload = self.record.to_dict()
        payload.update(
            {
                "score": round(float(self.final_score), 4),
                "name_score": round(float(self.name_score), 4),
                "fault_score": round(float(self.fault_score), 4),
                "service_type_adjustment": round(float(self.service_type_adjustment), 4),
            }
        )
        return payload


class ServiceProductRetriever:
    """基于 Qwen embedding 的服务商品多维度召回器。"""

    def __init__(
        self,
        excel_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
        embedding_client: QwenEmbeddingClient | None = None,
    ) -> None:
        self.excel_path = Path(excel_path or settings.spu_excel_path)
        self.cache_dir = Path(cache_dir or settings.embedding_cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_client = embedding_client or QwenEmbeddingClient()

        self._records: list[ServiceProductRecord] | None = None
        self._embeddings: dict[str, np.ndarray] = {}

    def search(
        self,
        query: str,
        product: str | None = None,
        fault: str | None = None,
        area: str | None = None,
        service_type_hint: str | None = None,
        top_k: int = 5,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        clean_query = self._build_query(query=query, product=product, fault=fault, area=area)
        if not clean_query:
            return []

        normalized_hint = service_type_hint or self.infer_service_type_hint(clean_query)
        query_embedding = self._normalize(self.embedding_client.embed_texts([clean_query]))[0]

        name_scores = self.embeddings("name") @ query_embedding
        fault_scores = self.embeddings("fault") @ query_embedding

        results: list[ServiceProductRecallResult] = []
        min_score = threshold if threshold is not None else settings.service_product_recall_threshold
        for index, record in enumerate(self.records):
            adjustment = self._service_type_adjustment(record, normalized_hint)
            final_score = (
                settings.service_product_name_weight * float(name_scores[index])
                + settings.service_product_fault_weight * float(fault_scores[index])
                + adjustment
            )
            if final_score < min_score:
                continue
            results.append(
                ServiceProductRecallResult(
                    final_score=final_score,
                    name_score=float(name_scores[index]),
                    fault_score=float(fault_scores[index]),
                    service_type_adjustment=adjustment,
                    record=record,
                )
            )

        ranked_results = sorted(results, key=lambda item: item.final_score, reverse=True)
        return [result.to_dict() for result in ranked_results[:top_k]]

    @property
    def records(self) -> list[ServiceProductRecord]:
        if self._records is None:
            self._records = SpuExcelLoader(self.excel_path).load()
        return self._records

    def embeddings(self, kind: str) -> np.ndarray:
        if kind not in EMBEDDING_KINDS:
            raise ValueError(f"Unsupported embedding kind: {kind}")
        if kind not in self._embeddings:
            self._embeddings[kind] = self._load_or_build_embeddings(kind)
        return self._embeddings[kind]

    def infer_service_type_hint(self, text: str) -> str | None:
        for service_type, keywords in SERVICE_TYPE_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return service_type
        return None

    def _load_or_build_embeddings(self, kind: str) -> np.ndarray:
        cache_path = self._cache_path(kind)
        metadata_path = cache_path.with_suffix(".json")
        current_metadata = self._cache_metadata(kind)

        if cache_path.exists() and metadata_path.exists():
            cached_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if cached_metadata == current_metadata:
                return np.load(cache_path)

        texts = [self._build_embedding_text(kind, record) for record in self.records]
        embeddings = self.embedding_client.embed_texts(texts)
        normalized_embeddings = self._normalize(embeddings)

        np.save(cache_path, normalized_embeddings)
        metadata_path.write_text(
            json.dumps(current_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized_embeddings

    def _build_embedding_text(self, kind: str, record: ServiceProductRecord) -> str:
        if kind == "name":
            values = [record.service_product_name]
        else:
            values = [record.fault_phenomenon]
        return self._join_text(values)

    def _service_type_adjustment(self, record: ServiceProductRecord, service_type_hint: str | None) -> float:
        if not service_type_hint:
            return 0.0
        if record.service_order_type == service_type_hint:
            return settings.service_type_match_bonus
        return -settings.service_type_mismatch_penalty

    def _cache_path(self, kind: str) -> Path:
        digest = hashlib.sha256(
            (
                f"{self.excel_path.resolve()}:{settings.qwen_embedding_model}:"
                f"{kind}:service-product-name-fault-v1"
            ).encode("utf-8")
        ).hexdigest()[:16]
        return self.cache_dir / f"service_product_{kind}_{digest}.npy"

    def _cache_metadata(self, kind: str) -> dict[str, Any]:
        stat = self.excel_path.stat()
        return {
            "kind": kind,
            "excel_path": str(self.excel_path.resolve()),
            "excel_mtime": stat.st_mtime,
            "excel_size": stat.st_size,
            "embedding_model": settings.qwen_embedding_model,
            "record_count": len(self.records),
            "text_builder_version": "service-product-name-fault-v1",
        }

    def _build_query(
        self,
        query: str,
        product: str | None,
        fault: str | None,
        area: str | None,
    ) -> str:
        return self._join_text([query, product or "", fault or "", area or ""])

    def _normalize(self, embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return embeddings / norms

    def _join_text(self, values: list[str]) -> str:
        return " ".join(value.strip() for value in values if value and value.strip())


@lru_cache
def get_service_product_retriever() -> ServiceProductRetriever:
    return ServiceProductRetriever()
