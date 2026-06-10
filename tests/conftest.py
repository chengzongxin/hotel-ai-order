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


def _trace_enabled(config: pytest.Config) -> bool:
    return bool(config.getoption("--trace-flow") or os.getenv("TRACE_TEST_STEPS") == "1")


def pytest_configure(config: pytest.Config) -> None:
    global _PYTEST_TRACE_ENABLED
    _PYTEST_TRACE_ENABLED = _trace_enabled(config)
    if _PYTEST_TRACE_ENABLED:
        # 只在显式追踪时关闭捕获，效果类似临时加 `-s`。
        config.option.capture = "no"


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
