from pydantic import BaseModel, Field


class ProductItem(BaseModel):
    """商品目录中的一个标准服务商品。"""

    service_product_code: str = Field(description="标准服务商品编码。", examples=["FWSP01537"])
    service_product_name: str = Field(description="标准服务商品名称。", examples=["门锁损坏（困客人）"])
    product_type: str = Field(description="商品类型。", examples=["维修"])
    category: str = Field(description="商品所属目录分类。")
    service_order_type: str = Field(description="商品对应的服务订单类型。", examples=["托管维修"])
    unit: str = Field(description="计价单位。", examples=["次"])
    price: str = Field(description="商品参考价格；字符串可保留上游展示格式。", examples=["48.08"])
    price_status: str = Field(description="价格状态或价格展示说明。")
    related_category: str = Field(description="商品关联的业务分类。")
    related_area: str = Field(description="商品适用的区域说明。")
    fault_phenomenon: str = Field(description="商品绑定的标准故障现象。")
    remark: str = Field(description="商品服务说明或备注。")


class ProductListResponse(BaseModel):
    """商品目录查询结果。"""

    total: int = Field(description="筛选后返回的商品总数。", ge=0)
    items: list[ProductItem] = Field(description="商品列表。")


class ProductSearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        description="用于召回标准服务商品的自然语言查询。",
        examples=["门锁打不开"],
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="最多返回的候选商品数量，范围 1～50。",
    )
    threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="可选的最低融合匹配分数，范围 0～1；为空时使用服务端默认值。",
    )


class ProductSearchResult(BaseModel):
    """商品检索命中的一个标准服务商品。"""

    score: float = Field(description="融合检索匹配分数，范围 0～1。", ge=0.0, le=1.0)
    service_product_code: str = Field(description="标准服务商品编码。", examples=["FWSP01537"])
    service_product_name: str = Field(description="标准服务商品名称。")
    service_order_type: str = Field(description="商品对应的服务订单类型。")
    product_type: str = Field(description="商品类型。")
    related_area: str = Field(description="商品适用的区域说明。")
    fault_phenomenon: str = Field(description="商品绑定的标准故障现象。")
    price: str = Field(description="商品参考价格。")
    unit: str = Field(description="计价单位。")


class ProductSearchResponse(BaseModel):
    """标准服务商品检索结果。"""

    query: str = Field(description="服务端实际执行的检索文本。")
    count: int = Field(description="本次返回的候选商品数量。", ge=0)
    products: list[ProductSearchResult] = Field(description="按匹配分数排序的候选商品。")
