from functools import lru_cache

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from config.settings import settings


@lru_cache
def get_llm() -> BaseChatModel:
    # 忽略系统 SOCKS/HTTP 代理，避免 Cursor 等 IDE 注入的本地代理导致 LLM 请求失败。
    http_async_client = httpx.AsyncClient(trust_env=False)
    return init_chat_model(
        model=settings.openai_model,
        model_provider="openai",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=settings.openai_temperature,
        model_kwargs={"extra_body": {"enable_thinking": False}},
        http_async_client=http_async_client,
    )
