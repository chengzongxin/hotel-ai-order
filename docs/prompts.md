# Prompt 目录说明

所有生产路径的 Prompt 均放在 `prompts/`，通过 `graph/prompts.py` 的 `load_prompt` / `render_prompt` 加载。

## 核心规则

> **一个 LangGraph 节点 → 一类 Prompt → 一个同名子目录**

| LangGraph 节点 | 子目录 | 主 Prompt（示例） |
| --- | --- | --- |
| `intent_node` | `prompts/intent/` | `intent/intent.md` |
| `ask_node` | `prompts/ask/` | `ask/missing_info.md` 等 |
| `assist_node` | `prompts/assist/` | `assist/assist.md` |
| `confirm_node` | `prompts/confirm/` | `confirm/confirm.md` |
| `submit_node` | `prompts/confirm/` | `confirm/submitted.md`（与确认同属下单收尾） |

说明：

- 子目录名去掉 `_node` 后缀，与节点一一对应（`intent_node` → `intent/`）。
- 该节点只有一份主 Prompt 时，可用 **`{目录}/{目录}.md`**（如 `intent/intent.md`、`assist/assist.md`）。
- 同一节点有多份 Prompt 时，仍在同一子目录下，用功能名区分（如 `ask/missing_info.md`、`ask/unknown_fallback.md`）。
- 跨节点但强相关的 Prompt 可放在最贴近的目录（如 `safety/off_topic.md` 服务于 `ask_node` 的偏题分支）。
- 新增节点时：先建 `prompts/<节点名>/`，再在代码里用 `render_prompt` / `load_prompt` 引用，不要把大段 Prompt 写进 Python。

## 其它约定

- **模板变量**：使用 `{{variable}}`，由 `render_prompt` 替换。
- **路径同步**：改文件名或目录后，更新 `graph/builder.py`、`graph/agent.py` 与本文件清单。

## 文件清单

| 路径 | 节点 / 用途 |
| --- | --- |
| `intent/intent.md` | `intent_node`：意图识别 + 槽位抽取 |
| `ask/missing_info.md` | `ask_node`：LLM 生成缺字段追问 |
| `ask/missing_info_retry.md` | `ask_node`：超过重试次数后的固定追问 |
| `ask/unknown_fallback.md` | `ask_node`：偏题引导 LLM 失败时的兜底文案 |
| `safety/off_topic.md` | `ask_node`：进行中订单时的偏题引导（LLM） |
| `confirm/confirm.md` | `confirm_node`：订单确认卡片 |
| `confirm/submitted.md` | `submit_node`：提交成功回复 |
| `assist/assist.md` | `assist_node`：辅助 Agent 系统提示 |

## 修改注意

- 改 `.md` 后需重启进程（`load_prompt` 带 `@lru_cache`）。
- 同步更新 `graph/builder.py` / `graph/agent.py` 中的路径与占位变量名。
