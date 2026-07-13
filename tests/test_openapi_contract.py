"""公开 API 的 OpenAPI 字段说明契约。"""

from typing import Any

from app.main import app


def _referenced_component_names(schema: Any) -> set[str]:
    """递归收集一个 OpenAPI schema 引用到的组件名。"""
    if isinstance(schema, list):
        names: set[str] = set()
        for item in schema:
            names.update(_referenced_component_names(item))
        return names
    if not isinstance(schema, dict):
        return set()

    names = set()
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        names.add(ref.rsplit("/", 1)[-1])
    for value in schema.values():
        names.update(_referenced_component_names(value))
    return names


def _successful_json_response_models(openapi: dict[str, Any]) -> set[str]:
    """收集所有成功 JSON 响应直接或间接使用的 Pydantic 模型。"""
    pending: list[str] = []
    for path_item in openapi["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            for status_code, response in operation["responses"].items():
                if not str(status_code).startswith("2"):
                    continue
                schema = response.get("content", {}).get("application/json", {}).get("schema")
                pending.extend(_referenced_component_names(schema))

    components = openapi["components"]["schemas"]
    discovered: set[str] = set()
    while pending:
        name = pending.pop()
        if name in discovered:
            continue
        discovered.add(name)
        pending.extend(_referenced_component_names(components[name]) - discovered)
    return discovered


def test_successful_response_fields_have_openapi_descriptions() -> None:
    """新增公开响应字段时，必须同时说明它的业务含义。"""
    openapi = app.openapi()
    components = openapi["components"]["schemas"]
    response_models = _successful_json_response_models(openapi)

    missing: list[str] = []
    for model_name in sorted(response_models):
        for field_name, field_schema in components[model_name].get("properties", {}).items():
            if not field_schema.get("description"):
                missing.append(f"{model_name}.{field_name}")

    assert not missing, "公开响应字段缺少 OpenAPI description: " + ", ".join(missing)


def test_order_preview_has_openapi_example() -> None:
    order_preview_schema = app.openapi()["components"]["schemas"]["OrderPreview"]

    assert order_preview_schema.get("examples"), "OrderPreview 应提供完整响应示例"

