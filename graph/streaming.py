"""流式事件与 LLM token 输出辅助。"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import uuid4

from langchain_core.messages import BaseMessage
from langgraph.config import get_stream_writer

from graph.llm import get_llm, get_llm_run_config

T = TypeVar("T")

MAX_TOOL_PAYLOAD_CHARS = 20_000
MAX_TOOL_DEPTH = 8
MAX_TOOL_LIST_ITEMS = 80
SENSITIVE_KEYWORDS = {
    "access_token",
    "authorization",
    "token",
    "secret",
    "password",
    "tenant",
    "phone",
    "mobile",
    "contacts",
    "contact",
    "address",
}
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")


def get_optional_stream_writer():
    try:
        return get_stream_writer()
    except RuntimeError:
        return None


def emit_status(step: str, message: str) -> None:
    writer = get_optional_stream_writer()
    if writer:
        writer({"type": "status", "step": step, "message": message})


def _mask_text(value: str) -> str:
    return PHONE_PATTERN.sub(lambda match: f"{match.group(1)[:3]}****{match.group(1)[-4:]}", value)


def _is_sensitive_key(key: object) -> bool:
    text = str(key).lower()
    return any(keyword in text for keyword in SENSITIVE_KEYWORDS)


def _json_size(value: object) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return len(str(value))


def _truncate_payload(value: object, max_chars: int = MAX_TOOL_PAYLOAD_CHARS) -> object:
    if _json_size(value) <= max_chars:
        return value
    preview = json.dumps(value, ensure_ascii=False, default=str)[:max_chars]
    return {
        "_truncated": True,
        "preview": preview,
        "message": f"payload exceeded {max_chars} characters and was truncated",
    }


def sanitize_tool_payload(value: object, *, depth: int = 0) -> object:
    """脱敏并裁剪工具调用事件中的参数和结果，避免把敏感信息推给前端。"""

    if depth > MAX_TOOL_DEPTH:
        return {"_truncated": True, "message": "max depth exceeded"}
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _mask_text(value)
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_sensitive_key(text_key):
                sanitized[text_key] = "***"
                continue
            sanitized[text_key] = sanitize_tool_payload(item, depth=depth + 1)
        return _truncate_payload(sanitized)
    if isinstance(value, list | tuple | set):
        items = list(value)
        sanitized_items = [sanitize_tool_payload(item, depth=depth + 1) for item in items[:MAX_TOOL_LIST_ITEMS]]
        if len(items) > MAX_TOOL_LIST_ITEMS:
            sanitized_items.append(
                {
                    "_truncated": True,
                    "message": f"{len(items) - MAX_TOOL_LIST_ITEMS} additional items omitted",
                }
            )
        return _truncate_payload(sanitized_items)
    return _truncate_payload(_mask_text(str(value)))


def _tool_status(result: object, default: str = "success") -> str:
    if isinstance(result, dict):
        status = result.get("status")
        if status:
            return str(status)
    return default


def _tool_summary(result: object, status: str) -> str:
    if isinstance(result, dict):
        message = result.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    if status == "success":
        return "调用成功"
    if status == "fallback":
        return "已使用兜底结果"
    if status == "error":
        return "调用失败"
    return "调用完成"


def emit_tool_call_event(
    *,
    phase: str,
    call_id: str,
    name: str,
    display_name: str | None = None,
    step: str | None = None,
    kind: str = "tool",
    status: str | None = None,
    params: object | None = None,
    result: object | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
    summary: str | None = None,
) -> None:
    writer = get_optional_stream_writer()
    if not writer:
        return

    event: dict[str, object] = {
        "type": "tool_call",
        "phase": phase,
        "call_id": call_id,
        "kind": kind,
        "name": name,
        "display_name": display_name or name,
    }
    if step:
        event["step"] = step
    if status:
        event["status"] = status
    if params is not None:
        event["params"] = sanitize_tool_payload(params)
    if result is not None:
        event["result"] = sanitize_tool_payload(result)
    if error:
        event["error"] = _mask_text(error)
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    if summary:
        event["summary"] = summary
    writer(event)


async def run_traced_tool_call(
    *,
    name: str,
    display_name: str,
    params: object,
    action: Callable[[], T | Awaitable[T]],
    step: str | None = None,
    kind: str = "tool",
    call_id: str | None = None,
) -> T:
    active_call_id = call_id or f"{step or 'tool'}:{name}:{uuid4().hex[:8]}"
    start = time.perf_counter()
    emit_tool_call_event(
        phase="start",
        call_id=active_call_id,
        name=name,
        display_name=display_name,
        step=step,
        kind=kind,
        status="running",
        params=params,
        summary="调用中",
    )
    try:
        result = action()
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        emit_tool_call_event(
            phase="error",
            call_id=active_call_id,
            name=name,
            display_name=display_name,
            step=step,
            kind=kind,
            status="error",
            params=params,
            error=repr(exc),
            duration_ms=duration_ms,
            summary="调用失败",
        )
        raise

    status = _tool_status(result)
    emit_tool_call_event(
        phase="end",
        call_id=active_call_id,
        name=name,
        display_name=display_name,
        step=step,
        kind=kind,
        status=status,
        params=params,
        result=result,
        duration_ms=(time.perf_counter() - start) * 1000,
        summary=_tool_summary(result, status),
    )
    return result


def message_chunk_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


async def emit_token_text(text: str, step: str, chunk_size: int = 4, delay_seconds: float = 0.015) -> None:
    writer = get_optional_stream_writer()
    if not writer:
        return

    for index in range(0, len(text), chunk_size):
        token = text[index : index + chunk_size]
        if token:
            writer({"type": "token", "step": step, "content": token})
            await asyncio.sleep(delay_seconds)


async def stream_llm_text(messages: list[BaseMessage], step: str) -> str:
    parts: list[str] = []
    async for chunk in get_llm().astream(messages, config=get_llm_run_config()):
        token = message_chunk_to_text(getattr(chunk, "content", ""))
        if not token:
            continue
        parts.append(token)
        await emit_token_text(token, step=step, chunk_size=4, delay_seconds=0)
    return "".join(parts).strip()
