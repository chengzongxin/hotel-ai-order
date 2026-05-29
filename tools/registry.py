from langchain_core.tools import BaseTool

from tools.check_package import check_package_tool
from tools.current_time import current_time
from tools.product_search import search_product_tool


def get_tools() -> list[BaseTool]:
    return [
        current_time,
        search_product_tool,
        check_package_tool,
    ]
