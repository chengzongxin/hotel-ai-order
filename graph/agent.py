from functools import lru_cache

from langchain.agents import create_agent

from graph.llm import get_llm
from graph.middleware import AGENT_MIDDLEWARE
from graph.prompts import load_prompt
from tools.registry import get_tools


@lru_cache
def get_assist_agent():
    """辅助 Agent，用于闲聊、商品查询等非主下单流程。"""

    return create_agent(
        model=get_llm(),
        tools=get_tools(),
        system_prompt=load_prompt("assist/assist.md"),
        middleware=AGENT_MIDDLEWARE,
        name="assist_agent",
    )
