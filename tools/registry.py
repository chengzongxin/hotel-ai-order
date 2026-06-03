from langchain_core.tools import BaseTool

from tools.check_package import check_package_tool
from tools.current_time import current_time
from tools.order_submit import submit_real_order_tool
from tools.product_search import search_product_tool
from tools.web_search import web_search_tool


def get_tools() -> list[BaseTool]:
    return [
        current_time,
        search_product_tool,
        submit_real_order_tool,
        check_package_tool,
        web_search_tool,
    ]
