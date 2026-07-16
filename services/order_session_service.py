"""Deterministic order commands issued by UI actions.

These commands update the same LangGraph checkpoint as conversational turns,
but they never ask an LLM to reinterpret an already explicit button click.
"""

import asyncio
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
from services.order_items import (
    add_or_merge_order_item,
    build_effective_order_info,
    build_order_info_for_item,
    build_order_state,
    find_order_item,
    get_order_items,
    get_order_common,
    product_from_order_item,
    split_order_info,
    strip_item_fields,
    sync_primary_item_from_order_info,
    validate_order_items,
)
from tools.order_payload_managed import align_order_second_area_with_spu
from services.order_normalizer import normalize_order_defaults
from services.order_workflow import OrderWorkflowService
from services.order_state import assert_order_state_invariants
from services.session_access import ensure_session_access
from rag.spu_loader import SpuExcelLoader

_SESSION_COMMAND_LOCKS: dict[tuple[str, str], asyncio.Lock] = {}


@asynccontextmanager
async def _order_session(
    session_id: str,
    user: UserContext,
) -> AsyncIterator[tuple[UserContext, Any, dict[str, object], dict[str, Any]]]:
    """Load and authorize one session while keeping its checkpoint open."""

    active_user = require_user(user)
    lock_key = (str(active_user.user_id), session_id)
    lock = _SESSION_COMMAND_LOCKS.setdefault(lock_key, asyncio.Lock())
    async with lock:
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
        if state.get("service_type") == "托管维修" and any(
            key in updates for key in ("area_room", "second_area", "room_number", "area", "fault")
        ):
            merged = {**state, **update}
            items = get_order_items(merged)
            primary = items[0]
            coverage_result = await OrderWorkflowService().check_hosting_product_coverage(
                order_info=build_order_info_for_item(get_order_common(merged), primary),
                matched_product=product_from_order_item(primary),
                user=active_user,
                last_user_message=str(state.get("last_user_message") or ""),
            )
            coverage_data = coverage_result.get("data") or {}
            effective_type = coverage_data.get("effective_service_type") or state.get("service_type")
            if len(items) > 1 and effective_type != state.get("service_type"):
                raise ValueError("修改后部分商品不在维保范围内，多商品订单不能混合托管和单次维修")
            primary["coverage"] = coverage_data
            update.update({
                "order": build_order_state(get_order_common(merged), items),
                "coverage_result": coverage_data,
                "effective_service_type": effective_type,
            })
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
        item_info = build_effective_order_info(state)
        if expected_type == "托管维修":
            coverage_result = await OrderWorkflowService().check_hosting_product_coverage(
                order_info=item_info,
                matched_product=product,
                user=user,
                last_user_message=str(state.get("last_user_message") or ""),
            )
            coverage_data = coverage_result.get("data") or {}
            if coverage_data.get("effective_service_type") != "托管维修":
                raise ValueError("该商品不在当前维保范围内，不能加入此托管维修订单")
            spu_detail = coverage_data.get("spu_detail") if isinstance(coverage_data.get("spu_detail"), dict) else {}
            if spu_detail:
                item_info, area_match = align_order_second_area_with_spu(
                    item_info, spu_detail, source_text=str(state.get("last_user_message") or "")
                )
                coverage_data = {**coverage_data, "area_match": area_match}
        else:
            coverage_data = {
                "checked": False,
                "covered": None,
                "reason": "非托管维修商品，无需校验维保卡范围",
                "effective_service_type": expected_type,
            }
        order_items = add_or_merge_order_item(
            get_order_items(state),
            product,
            item_info,
            quantity,
        )
        added = next(item for item in order_items if item.get("product_code") == product_code)
        added["coverage"] = coverage_data
        order_items, _ = validate_order_items(get_effective_service_type(state), get_order_common(state), order_items)
        update = {"order": build_order_state(get_order_common(state), order_items), "submission": empty_submission()}
        assert_order_state_invariants({**state, **update})
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
        if state.get("service_type") == "托管维修" and "fault" in updates:
            coverage_result = await OrderWorkflowService().check_hosting_product_coverage(
                order_info=build_order_info_for_item(get_order_common(state), item),
                matched_product=product_from_order_item(item),
                user=user,
                last_user_message=str(state.get("last_user_message") or ""),
            )
            item["coverage"] = coverage_result.get("data") or {}
        items, _ = validate_order_items(get_effective_service_type(state), get_order_common(state), items)
        for validated in items:
            coverage = validated.get("coverage") if isinstance(validated.get("coverage"), dict) else {}
            if state.get("service_type") == "托管维修" and coverage.get("covered") is not True:
                validation = validated.get("validation") or {}
                missing = list(validation.get("missing_fields") or [])
                if "coverage" not in missing:
                    missing.append("coverage")
                validated["validation"] = {"valid": False, "missing_fields": missing}
        update = {"order": build_order_state(get_order_common(state), items), "submission": empty_submission()}
        assert_order_state_invariants({**state, **update})
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
        remaining, _ = validate_order_items(
            get_effective_service_type(state),
            get_order_common(state),
            [item for item in items if str(item.get("id")) != item_id],
        )
        update = {"order": build_order_state(get_order_common(state), remaining), "submission": empty_submission()}
        assert_order_state_invariants({**state, **update})
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
                **build_effective_order_info(state),
                "user_confirmed": True,
                "user_cancelled": False,
            },
            last_user_message=state.get("last_user_message", ""),
        )
        updated_items = sync_primary_item_from_order_info(get_order_items(state), order_info)
        updated_items, item_missing = validate_order_items(service_type, strip_item_fields(order_info), updated_items)
        confirmed_state_patch = {
            **split_order_info(order_info, keep_product_request=False),
            "order": build_order_state(strip_item_fields(order_info), updated_items),
            "phase": PHASE_PRE_ORDER,
        }
        missing_info = collect_missing_order_info(
            service_type,
            order_info,
            state.get("order_card_fields") or [],
        )
        missing_info.extend(field for field in item_missing if field not in missing_info)
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
        submitting = {**empty_submission(), "attempted": True, "state": "submitting"}
        await graph.aupdate_state(config, {"submission": submitting}, as_node="confirm_node")
        confirmed_state["submission"] = submitting
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
