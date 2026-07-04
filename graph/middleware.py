import inspect
import time
from typing import Any
from uuid import uuid4

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
    wrap_model_call,
    wrap_tool_call,
)

from graph.streaming import emit_tool_call_event
from utils.logger_handler import trace_logger


@wrap_model_call
async def log_model_call(request: Any, handler: Any) -> Any:
    start = time.perf_counter()
    trace_logger(
        "agent.middleware.llm.before",
        message_count=len(request.messages),
        tool_count=len(request.tools or []),
    )
    try:
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        trace_logger("agent.middleware.llm.error", error=repr(exc))
        raise

    trace_logger(
        "agent.middleware.llm.after",
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        result_preview=str(result)[:1000],
    )
    return result


@wrap_tool_call
async def log_tool_call(request: Any, handler: Any) -> Any:
    start = time.perf_counter()
    tool_call = request.tool_call or {}
    tool_name = str(tool_call.get("name") or "unknown_tool")
    call_id = str(tool_call.get("id") or f"assist_node:{tool_name}:{uuid4().hex[:8]}")
    tool_args = tool_call.get("args")
    trace_logger(
        "agent.middleware.tool.before",
        tool_name=tool_name,
        tool_args=tool_args,
    )
    emit_tool_call_event(
        phase="start",
        call_id=call_id,
        name=tool_name,
        display_name=tool_name,
        step="assist_node",
        status="running",
        params=tool_args,
        summary="调用中",
    )
    try:
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        trace_logger(
            "agent.middleware.tool.error",
            tool_name=tool_name,
            error=repr(exc),
        )
        emit_tool_call_event(
            phase="error",
            call_id=call_id,
            name=tool_name,
            display_name=tool_name,
            step="assist_node",
            status="error",
            params=tool_args,
            error=repr(exc),
            duration_ms=duration_ms,
            summary="调用失败",
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000
    trace_logger(
        "agent.middleware.tool.after",
        tool_name=tool_name,
        duration_ms=round(duration_ms, 2),
        result_preview=str(result)[:1000],
    )
    emit_tool_call_event(
        phase="end",
        call_id=call_id,
        name=tool_name,
        display_name=tool_name,
        step="assist_node",
        status="success",
        params=tool_args,
        result=result,
        duration_ms=duration_ms,
        summary="调用成功",
    )
    return result


AGENT_MIDDLEWARE = [
    log_model_call,
    log_tool_call,
    ModelRetryMiddleware(max_retries=1),
    ToolRetryMiddleware(max_retries=1),
    ModelCallLimitMiddleware(run_limit=3, exit_behavior="end"),
    ToolCallLimitMiddleware(run_limit=3, exit_behavior="continue"),
]
