"""商品召回 BM25 / 混合排序纯逻辑测试（无 embedding 依赖）。"""

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from rag.product_store import (
    BM25_SCORE_WEIGHT,
    NO_FAULT_PENALTY,
    VECTOR_SCORE_WEIGHT,
    ProductVectorStore,
    _compute_hybrid_score,
    _normalize_score_map,
    _tokenize_for_bm25,
)


def test_tokenize_for_bm25_filters_empty_tokens():
    tokens = _tokenize_for_bm25("空调 漏水")
    assert "空调" in tokens
    assert "漏水" in tokens
    assert "" not in tokens


def test_normalize_score_map():
    normalized = _normalize_score_map({"a": 2.0, "b": 1.0, "c": 0.0})
    assert normalized["a"] == 1.0
    assert normalized["b"] == 0.5
    assert normalized["c"] == 0.0


def test_compute_hybrid_score():
    score = _compute_hybrid_score(0.8, 1.0)
    assert score == VECTOR_SCORE_WEIGHT * 0.8 + BM25_SCORE_WEIGHT * 1.0


def test_bm25_prefers_ac_over_water_cabinet():
    corpus = [
        _tokenize_for_bm25("空调 小修"),
        _tokenize_for_bm25("水柜 中修"),
        _tokenize_for_bm25("门锁 损坏"),
    ]
    bm25 = BM25Okapi(corpus)
    query_tokens = _tokenize_for_bm25("空调 漏水")
    scores = bm25.get_scores(query_tokens)
    assert scores[0] > scores[1]
    assert scores[1] == 0.0


def test_merge_hybrid_candidates_deduplicates_by_product_code():
    store = ProductVectorStore.__new__(ProductVectorStore)
    doc_a = Document(
        page_content="门锁",
        metadata={"service_product_code": "A", "service_product_name": "门锁(小修)"},
    )
    doc_b = Document(
        page_content="空调",
        metadata={"service_product_code": "B", "service_product_name": "空调(小修)"},
    )
    store._documents = [doc_a, doc_b]

    merged = store._merge_hybrid_candidates(
        vector_results=[(doc_a, 0.9)],
        bm25_results=[(0, 3.5), (1, 1.2)],
    )

    assert set(merged.keys()) == {"A", "B"}
    assert merged["A"]["vector_score"] == 0.9
    assert merged["A"]["bm25_score"] == 3.5
    assert merged["B"]["vector_score"] == 0.0
    assert merged["B"]["bm25_score"] == 1.2


def test_no_fault_penalty_constant():
    assert NO_FAULT_PENALTY == 0.15
