"""Deterministic order commands issued by UI actions.

These commands update the same LangGraph checkpoint as conversational turns,
but they never ask an LLM to reinterpret an already explicit button click.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.messages import AIMessage

from graph.builder import (
    build_graph,
    build_missing_info_fallback_question,
    cancel_node,
    has_active_order,
)
from graph.checkpoint import checkpoint_path, get_graph_config
from graph.constants import PHASE_PRE_ORDER, PHASE_PRODUCT_SELECTION
from graph.order_fields import collect_missing_order_info
from graph.products import find_product_by_code
from graph.submission import empty_submission, get_effective_service_type, submit_order_from_state
from memory.postgres_log import save_conversation_log
from memory.readable_sqlite_saver import ReadableAsyncSqliteSaver
from schemas.user import SessionAccessError, UserContext, require_user
from services.conversation_service import (
    build_conversation_turn,
    update_active_conversation_preview,
)
from services.order_items import add_or_merge_order_item, find_order_item, get_order_items
from services.order_normalizer import normalize_order_defaults
from services.order_workflow import OrderWorkflowService
from services.session_access import ensure_session_access
from rag.spu_loader import SpuExcelLoader


@asynccontextmanager
async def _order_session(
    session_id: str,
    user: UserContext,
) -> AsyncIterator[tuple[UserContext, Any, dict[str, object], dict[str, Any]]]:
    """Load and authorize one session while keeping its checkpoint open."""

    active_user = require_user(user)
    async with ReadableAsyncSqliteSaver.from_conn_string(str(checkpoint_path())) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer)
        config = get_graph_config(active_user, session_id)
        snapshot = await graph.aget_state(config)
        state = snapshot.values or {}
        if not state:
            raise SessionAccessError("会话不存在或尚未开始对话")
        ensure_session_access(state, active_user)
        yield active_user, graph, config, state


async def select_product_in_session(
    session_id: str,
    product_code: str,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (active_user, graph, config, state):
        if state.get("phase") != PHASE_PRODUCT_SELECTION:
            raise ValueError("当前阶段不能选择商品")

        update = await OrderWorkflowService().select_product(
            state=state,
            product_code=product_code,
            user=active_user,
        )
        await graph.aupdate_state(config, update, as_node="search_product_node")
        merged_state = {**state, **update}

        selected = find_product_by_code(state.get("products") or [], product_code) or {}
        product_name = selected.get("service_product_name") or product_code
        repair_level = (
            selected.get("repair_category")
            or selected.get("product_type")
            or selected.get("service_order_type")
            or "待确认"
        )
        message = f"好的，已为您选择【{product_name}（{repair_level}）】，正在生成预下单卡片。"
        missing_info = update.get("missing_info") or []
        if isinstance(missing_info, list) and missing_info:
            message = f"{message}\n{build_missing_info_fallback_question(missing_info)}"
        conversation_messages = build_conversation_turn(
            human_content=f"选择商品：{product_name}",
            ai_content=message,
            state=merged_state,
        )
        if conversation_messages[-1]["order_preview"] is None:
            raise ValueError("更新商品后无法生成订单预览")
        await graph.aupdate_state(
            config,
            {"conversation_messages": conversation_messages},
            as_node="ask_node",
        )
        await save_conversation_log(session_id, "human", f"选择商品：{product_name}")
        await save_conversation_log(session_id, "ai", message)
        return {
            "session_id": session_id,
            "conversation_messages": conversation_messages,
        }


async def reject_products_in_session(
    session_id: str,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (_, graph, config, state):
        if state.get("phase") != PHASE_PRODUCT_SELECTION or not state.get("products"):
            raise ValueError("当前没有可拒绝的商品候选")

        answer = "好的，请重新描述需要处理的商品和具体问题。"
        update = {
            **OrderWorkflowService().reject_products(service_type=state.get("service_type")),
            "messages": [AIMessage(content=answer)],
        }
        await graph.aupdate_state(config, update, as_node="search_product_node")
        merged_state = {**state, **update}
        conversation_messages = build_conversation_turn(
            human_content="以上都不符合",
            ai_content=answer,
            state=merged_state,
        )
        await graph.aupdate_state(
            config,
            {"conversation_messages": conversation_messages},
            as_node="ask_node",
        )
        await save_conversation_log(session_id, "human", "以上都不符合")
        await save_conversation_log(session_id, "ai", answer)
        return {
            "session_id": session_id,
            "conversation_messages": conversation_messages,
        }


async def update_order_info_in_session(
    session_id: str,
    updates: dict[str, object],
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (active_user, graph, config, state):
        if state.get("phase") != PHASE_PRE_ORDER:
            raise ValueError("当前阶段不能修改预下单信息")

        service_type = get_effective_service_type(state)
        update = await OrderWorkflowService().update_order_card(
            state=state,
            updates=updates,
            service_type=service_type,
            user=active_user,
        )
        await graph.aupdate_state(config, update, as_node="prepare_order_context_node")
        merged_state = {**state, **update}
        conversation_message = update_active_conversation_preview(
            messages=state.get("conversation_messages") or [],
            state=merged_state,
            fallback_content="已更新预下单信息。",
        )
        if conversation_message["order_preview"] is None:
            raise ValueError("更新下单信息后无法生成订单预览")
        await graph.aupdate_state(
            config,
            {"conversation_messages": [conversation_message]},
            as_node="ask_node",
        )
        return {
            "session_id": session_id,
            "conversation_messages": [conversation_message],
        }


async def add_order_item_in_session(
    session_id: str,
    product_code: str,
    quantity: int,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (_, graph, config, state):
        if state.get("phase") != PHASE_PRE_ORDER:
            raise ValueError("当前阶段不能新增商品")
        product = next(
            (record.to_dict() for record in SpuExcelLoader().load() if record.service_product_code == product_code),
            None,
        )
        if not product:
            raise ValueError(f"商品 {product_code} 不存在或已下架")
        expected_type = state.get("service_type")
        if expected_type and product.get("service_order_type") != expected_type:
            raise ValueError(f"只能添加同为【{expected_type}】的商品")
        if get_effective_service_type(state) != expected_type:
            raise ValueError("维保范围外已转为单次订单，暂不能与托管维修商品合并下单")
        order_items = add_or_merge_order_item(
            get_order_items(state),
            product,
            state.get("order_info") or {},
            quantity,
        )
        update = {"order_items": order_items, "submission": empty_submission()}
        await graph.aupdate_state(config, update, as_node="prepare_order_context_node")
        message = update_active_conversation_preview(
            messages=state.get("conversation_messages") or [],
            state={**state, **update},
            fallback_content="已更新预下单商品。",
        )
        await graph.aupdate_state(config, {"conversation_messages": [message]}, as_node="ask_node")
        return {"session_id": session_id, "conversation_messages": [message]}


async def update_order_item_in_session(
    session_id: str,
    item_id: str,
    updates: dict[str, object],
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (_, graph, config, state):
        if state.get("phase") != PHASE_PRE_ORDER:
            raise ValueError("当前阶段不能修改商品")
        items = get_order_items(state)
        item = find_order_item(items, item_id)
        if not item:
            raise ValueError("订单商品不存在")
        if updates.get("quantity") is not None:
            item["quantity"] = max(int(updates["quantity"]), 1)
        if "fault" in updates:
            item["fault"] = str(updates.get("fault") or "").strip() or None
        update = {"order_items": items, "submission": empty_submission()}
        await graph.aupdate_state(config, update, as_node="prepare_order_context_node")
        message = update_active_conversation_preview(
            messages=state.get("conversation_messages") or [], state={**state, **update}, fallback_content="已更新预下单商品。"
        )
        await graph.aupdate_state(config, {"conversation_messages": [message]}, as_node="ask_node")
        return {"session_id": session_id, "conversation_messages": [message]}


async def remove_order_item_in_session(
    session_id: str,
    item_id: str,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (_, graph, config, state):
        if state.get("phase") != PHASE_PRE_ORDER:
            raise ValueError("当前阶段不能删除商品")
        items = get_order_items(state)
        if len(items) <= 1:
            raise ValueError("订单至少需要保留一个商品")
        if not find_order_item(items, item_id):
            raise ValueError("订单商品不存在")
        update = {"order_items": [item for item in items if str(item.get("id")) != item_id], "submission": empty_submission()}
        await graph.aupdate_state(config, update, as_node="prepare_order_context_node")
        message = update_active_conversation_preview(
            messages=state.get("conversation_messages") or [], state={**state, **update}, fallback_content="已更新预下单商品。"
        )
        await graph.aupdate_state(config, {"conversation_messages": [message]}, as_node="ask_node")
        return {"session_id": session_id, "conversation_messages": [message]}


async def confirm_order_in_session(
    session_id: str,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (active_user, graph, config, state):
        if state.get("phase") != PHASE_PRE_ORDER:
            raise ValueError("当前阶段不能确认下单")

        if not get_order_items(state):
            raise ValueError("请先选择商品，再确认下单")

        service_type = get_effective_service_type(state)
        order_info = normalize_order_defaults(
            service_type=service_type,
            order_info={
                **(state.get("order_info") or {}),
                "user_confirmed": True,
                "user_cancelled": False,
            },
            last_user_message=state.get("last_user_message", ""),
        )
        confirmed_state_patch = {
            "order_info": order_info,
            "phase": PHASE_PRE_ORDER,
        }
        missing_info = collect_missing_order_info(
            service_type,
            order_info,
            state.get("order_card_fields") or [],
        )
        if missing_info:
            answer = build_missing_info_fallback_question(missing_info)
            update = {
                **confirmed_state_patch,
                "missing_info": missing_info,
                "submission": empty_submission(),
            }
            await graph.aupdate_state(config, update, as_node="validate_order_node")
            conversation_messages = build_conversation_turn(
                human_content="确认下单",
                ai_content=answer,
                state={**state, **update},
            )
            await graph.aupdate_state(
                config,
                {"conversation_messages": conversation_messages},
                as_node="ask_node",
            )
            await save_conversation_log(session_id, "human", "确认下单")
            await save_conversation_log(session_id, "ai", answer)
            return {
                "session_id": session_id,
                "conversation_messages": conversation_messages,
            }

        confirmed_state = {
            **state,
            **confirmed_state_patch,
            "missing_info": [],
        }
        submit_update = await submit_order_from_state(
            confirmed_state,
            active_user,
            emit=False,
        )
        await graph.aupdate_state(config, submit_update, as_node="submit_node")
        answer_messages = submit_update.get("messages") or []
        answer = str(answer_messages[-1].content) if answer_messages else "已处理确认下单请求。"
        final_state = {**confirmed_state, **submit_update}
        conversation_messages = build_conversation_turn(
            human_content="确认下单",
            ai_content=answer,
            state=final_state,
        )
        await graph.aupdate_state(
            config,
            {"conversation_messages": conversation_messages},
            as_node="ask_node",
        )
        await save_conversation_log(session_id, "human", "确认")
        await save_conversation_log(session_id, "ai", answer)
        return {
            "session_id": session_id,
            "conversation_messages": conversation_messages,
        }


async def cancel_order_in_session(
    session_id: str,
    user: UserContext,
) -> dict[str, object]:
    async with _order_session(session_id, user) as (_, graph, config, state):
        if not has_active_order(state):
            raise ValueError("当前没有可取消的订单")

        update = await cancel_node(state)
        await graph.aupdate_state(config, update, as_node="cancel_node")
        answer_messages = update.get("messages") or []
        answer = str(answer_messages[-1].content) if answer_messages else "已取消当前订单。"
        conversation_messages = build_conversation_turn(
            human_content="取消订单",
            ai_content=answer,
            state={**state, **update},
        )
        await graph.aupdate_state(
            config,
            {"conversation_messages": conversation_messages},
            as_node="ask_node",
        )
        await save_conversation_log(session_id, "human", "取消订单")
        await save_conversation_log(session_id, "ai", answer)
        return {
            "session_id": session_id,
            "conversation_messages": conversation_messages,
        }
