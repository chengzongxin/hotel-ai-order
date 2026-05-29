import inspect
import time
from functools import lru_cache
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from config.logging import trace_event
from config.settings import settings
from tools.registry import get_tools


@lru_cache
def get_agent_llm() -> BaseChatModel:
    return init_chat_model(
        model=settings.openai_model,
        model_provider="openai",
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        temperature=settings.openai_temperature,
    )


@wrap_model_call
async def log_model_call(request: Any, handler: Any) -> Any:
    start = time.perf_counter()
    trace_event(
        "agent.middleware.llm.before",
        message_count=len(request.messages),
        tool_count=len(request.tools or []),
    )
    try:
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        trace_event("agent.middleware.llm.error", error=repr(exc))
        raise

    trace_event(
        "agent.middleware.llm.after",
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        result_preview=str(result)[:1000],
    )
    return result


@wrap_tool_call
async def log_tool_call(request: Any, handler: Any) -> Any:
    start = time.perf_counter()
    tool_call = request.tool_call or {}
    trace_event(
        "agent.middleware.tool.before",
        tool_name=tool_call.get("name"),
        tool_args=tool_call.get("args"),
    )
    try:
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        trace_event(
            "agent.middleware.tool.error",
            tool_name=tool_call.get("name"),
            error=repr(exc),
        )
        raise

    trace_event(
        "agent.middleware.tool.after",
        tool_name=tool_call.get("name"),
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        result_preview=str(result)[:1000],
    )
    return result


@lru_cache
def get_assist_agent():
    """官方 LangChain middleware agent，用于非主下单流程的辅助问答。"""

    return create_agent(
        model=get_agent_llm(),
        tools=get_tools(),
        system_prompt=(
            "你是酒店 AI 下单助手的辅助 Agent。"
            "你可以回答用户的简单问题，也可以在需要时调用工具查询。"
            "如果用户询问商品或设备相关信息，可调用 search_product_tool 查询商品库，"
            "商品库涵盖维修、安装、测量、托管维修等服务类型。"
            "不要直接提交订单；如果用户要下单，请引导用户提供房号、商品和问题。"
        ),
        middleware=[
            log_model_call,
            log_tool_call,
            ModelRetryMiddleware(max_retries=1),
            ToolRetryMiddleware(max_retries=1),
            ModelCallLimitMiddleware(run_limit=3, exit_behavior="end"),
            ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
        ],
        name="assist_agent",
    )
