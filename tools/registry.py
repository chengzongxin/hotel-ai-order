from langchain_core.tools import BaseTool

from tools.basic import current_time, echo
from tools.maintenance import check_package_tool, create_order_tool, search_product_tool
from tools.qdrant_placeholder import qdrant_status
from tools.product_match import match_product_tool


def get_tools() -> list[BaseTool]:
    return [
        current_time,
        echo,
        search_product_tool,
        match_product_tool,
        check_package_tool,
        create_order_tool,
        qdrant_status,
    ]
