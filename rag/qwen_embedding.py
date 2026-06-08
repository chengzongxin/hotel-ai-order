from typing import Any

import httpx
import numpy as np

from config.settings import settings

QWEN_MAX_BATCH_SIZE = 10


class QwenEmbeddingClient:
    """Qwen text-embedding 客户端。

    这里使用 DashScope 的 OpenAI-compatible `/embeddings` 接口。
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.model = model or settings.qwen_embedding_model
        self.base_url = (base_url or settings.qwen_embedding_base_url).rstrip("/")
        self.api_key = api_key or settings.qwen_embedding_api_key or settings.openai_api_key
        self.timeout_seconds = timeout_seconds or settings.qwen_embedding_timeout_seconds

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        clean_texts = [text.strip() for text in texts]
        if not clean_texts:
            return np.empty((0, 0), dtype=np.float32)
        if not self.api_key:
            raise ValueError("Qwen embedding API key is not configured")

        batch_size = min(settings.qwen_embedding_batch_size, QWEN_MAX_BATCH_SIZE)
        embeddings: list[list[float]] = []
        for start in range(0, len(clean_texts), batch_size):
            batch = clean_texts[start : start + batch_size]
            embeddings.extend(self._embed_batch(batch))

        return np.asarray(embeddings, dtype=np.float32)

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(trust_env=False, timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": texts,
                },
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:500]
            raise RuntimeError(
                f"Qwen embedding request failed: {response.status_code} {body}"
            ) from exc
        payload: dict[str, Any] = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in data]
