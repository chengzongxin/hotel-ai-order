from pydantic import BaseModel, Field


class ProductItem(BaseModel):
    service_product_code: str
    service_product_name: str
    product_type: str
    category: str
    service_order_type: str
    unit: str
    price: str
    price_status: str
    related_category: str
    related_area: str
    fault_phenomenon: str
    remark: str


class ProductListResponse(BaseModel):
    total: int
    items: list[ProductItem]


class ProductSearchRequest(BaseModel):
    query: str
    product: str | None = None
    fault: str | None = None
    area: str | None = None
    service_type_hint: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class ProductSearchResult(BaseModel):
    score: float
    service_product_code: str
    service_product_name: str
    service_order_type: str
    product_type: str
    related_area: str
    fault_phenomenon: str
    price: str
    unit: str


class ProductSearchResponse(BaseModel):
    query: str
    count: int
    results: list[ProductSearchResult]
