"""商品召回 golden set 评测（需真实 embedding + chroma_db）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rag.product_store import ProductVectorStore

RECALL_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "product_recall_cases.json"
_RECALL_CASES: list[dict[str, Any]] = json.loads(RECALL_FIXTURE_PATH.read_text(encoding="utf-8"))["cases"]


def _name_contains(name: str, keywords: list[str]) -> bool:
    return any(keyword in name for keyword in keywords)


@pytest.mark.embedding
@pytest.mark.parametrize("case", _RECALL_CASES, ids=[case["id"] for case in _RECALL_CASES])
def test_product_recall_eval(case: dict[str, Any]):
    store = ProductVectorStore()
    top_k = case.get("top_k", 5)
    threshold = case.get("threshold")

    results = store.search(
        query=case["query"],
        top_k=top_k,
        threshold=threshold,
    )

    expected = case.get("expected") or {}
    min_results = expected.get("min_results", 1)
    assert len(results) >= min_results, f"{case['id']}: expected at least {min_results} results"

    if expected.get("top1_name_contains"):
        top1_name = results[0].get("service_product_name") or ""
        assert _name_contains(top1_name, expected["top1_name_contains"]), (
            f"{case['id']}: top1={top1_name!r} missing {expected['top1_name_contains']}"
        )

    if expected.get("top1_service_order_type"):
        actual = results[0].get("service_order_type") or results[0].get("service_order_type")
        assert actual == expected["top1_service_order_type"], case["id"]

    if expected.get("top3_forbidden_name_contains"):
        for item in results[:3]:
            name = item.get("service_product_name") or ""
            for forbidden in expected["top3_forbidden_name_contains"]:
                assert forbidden not in name, f"{case['id']}: top3 contains forbidden {forbidden!r} in {name!r}"

    if expected.get("any_top_k_name_contains"):
        names = [item.get("service_product_name") or "" for item in results[:top_k]]
        assert any(
            _name_contains(name, expected["any_top_k_name_contains"]) for name in names
        ), f"{case['id']}: none of top_k matched {expected['any_top_k_name_contains']}"
