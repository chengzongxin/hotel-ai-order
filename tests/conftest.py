"""pytest 共享配置。"""

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


# 让 `uv run pytest` 可以直接从项目根目录导入 graph/api/tools 等本地模块。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_PYTEST_TRACE_ENABLED = False


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return repr(value)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--trace-flow",
        action="store_true",
        default=False,
        help="打印自动化测试的调用步骤、输入和输出。",
    )
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="运行需要真实 LLM API 的集成测试。",
    )
    parser.addoption(
        "--run-embedding",
        action="store_true",
        default=False,
        help="运行需要 Qwen embedding 与 chroma_db 的商品召回评测。",
    )
    parser.addoption(
        "--run-real-submit",
        action="store_true",
        default=False,
        help="运行会真实创建订单的端到端测试。",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _PYTEST_TRACE_ENABLED
    _PYTEST_TRACE_ENABLED = _trace_enabled(config)
    if _PYTEST_TRACE_ENABLED:
        config.option.capture = "no"
    config.addinivalue_line("markers", "llm: requires real Chat LLM API")
    config.addinivalue_line("markers", "embedding: requires Qwen embedding + chroma_db")
    config.addinivalue_line("markers", "e2e: full run_agent integration")
    config.addinivalue_line("markers", "real_submit: creates a real order through the configured order API")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_llm = config.getoption("--run-llm")
    run_embedding = config.getoption("--run-embedding")
    run_real_submit = config.getoption("--run-real-submit")

    skip_llm = pytest.mark.skip(reason="需要 --run-llm 才运行真实 LLM 集成测试")
    skip_embedding = pytest.mark.skip(reason="需要 --run-embedding 才运行商品召回 embedding 评测")
    skip_real_submit = pytest.mark.skip(reason="需要 --run-real-submit 才运行会真实创建订单的测试")

    for item in items:
        if "llm" in item.keywords and not run_llm:
            item.add_marker(skip_llm)
        if "embedding" in item.keywords and not run_embedding:
            item.add_marker(skip_embedding)
        if "real_submit" in item.keywords and not run_real_submit:
            item.add_marker(skip_real_submit)


def _trace_enabled(config: pytest.Config) -> bool:
    return bool(config.getoption("--trace-flow") or os.getenv("TRACE_TEST_STEPS") == "1")


def pytest_runtest_setup(item: pytest.Item) -> None:
    if _PYTEST_TRACE_ENABLED:
        terminal = item.config.pluginmanager.get_plugin("terminalreporter")
        if terminal:
            terminal.write_line(f"\n========== TEST START: {item.nodeid} ==========")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call":
        return
    if not _PYTEST_TRACE_ENABLED:
        return
    status = "PASSED" if report.passed else "FAILED" if report.failed else "SKIPPED"
    print(f"========== TEST {status}: {report.nodeid} ({report.duration:.3f}s) ==========")


@pytest.fixture
def trace_step(request: pytest.FixtureRequest):
    """打印测试步骤、输入和输出，方便观察自动化调用过程。"""

    def _trace_step(title: str, **payload: Any) -> None:
        if not _trace_enabled(request.config):
            return
        terminal = request.config.pluginmanager.get_plugin("terminalreporter")
        lines = [f"\n--- {title} ---"]
        for key, value in payload.items():
            lines.append(f"{key}: {_safe_json(value)}")
        text = "\n".join(lines)
        if terminal:
            terminal.write_line(text)
        else:
            print(text)

    return _trace_step
