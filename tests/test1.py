import operator
from typing import Dict, TypedDict, Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, MessagesState, START, END

class MessagesState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    x: int
    y: int

def mock_llm(state: Dict):
    return {"x": state["x"] + 1, "y": state["y"] + 1}

graph = StateGraph(MessagesState)
graph.add_node(mock_llm)
graph.add_edge(START, "mock_llm")
graph.add_edge("mock_llm", END)
graph = graph.compile()

app = graph.invoke({"x": 1, "y": 2})
print("====================")
print(app)
print("====================")


import jieba
print(list(jieba.cut_for_search("门把手 坏了")))
print(list(jieba.lcut("门把手 坏了")))


print("-----------")

print(list(jieba.lcut("门五金")))
print(list(jieba.cut_for_search("门五金")))

