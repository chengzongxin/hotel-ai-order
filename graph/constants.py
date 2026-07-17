"""LangGraph 状态机常量与阶段定义。"""

MAX_RETRY_COUNT = 2

CANCEL_ORDER_KEYWORDS = ("取消", "不用了", "不提交", "先算了", "撤销", "放弃", "不要了")
PUBLIC_AREA_KEYWORDS = (
    "公区",
    "公共区域",
    "大厅",
    "大堂",
    "接待区",
    "公区卫生间",
    "公共厕所",
    "布草间",
    "办公室",
    "洗衣房",
    "员工区",
    "走廊",
    "过道",
    "电梯",
    "电梯厅",
    "前台",
    "餐厅",
    "会议室",
    "楼梯间",
    "楼顶",
    "健身房",
    "停车场",
    "仓库",
    "设备间",
)
GUEST_ROOM_KEYWORDS = (
    "客房",
    "房间",
    "房里",
    "屋内",
    "住客区",
    "维修房",
    "客房楼层",
    "卫生间",
    "淋浴间",
)
PUBLIC_SECOND_AREA_KEYWORDS = {
    "楼顶": ("楼顶", "天台", "屋顶"),
    "电梯": ("电梯", "电梯厅", "轿厢"),
    "客房走廊": ("客房走廊", "走廊", "过道"),
    "办公室": ("办公室", "办公区"),
    "布草间": ("布草间", "布草房"),
    "洗衣房": ("洗衣房", "洗衣间"),
    "卫生间区域": ("公区卫生间", "公共厕所", "公厕", "公共卫生间"),
    "健身房": ("健身房",),
    "餐厅": ("餐厅", "食堂"),
    "大堂": ("大堂", "大厅", "前台", "接待区"),
}
GUEST_SECOND_AREA_KEYWORDS = {
    "卫生间区域": ("卫生间", "洗手间", "浴室", "淋浴间", "厕所", "马桶"),
    "客房设备": ("客房设备", "房间设备", "屋内设备", "空调", "电视", "冰箱", "门锁", "窗帘", "灯", "插座"),
    "客房区域": ("客房区域", "客房", "房间", "房里", "屋内", "住客区", "维修房", "客房楼层"),
}
VALID_MANAGED_REPAIR_SCOPES = {"客房", "公区"}
PHASE_IDLE = "idle"
PHASE_PRODUCT_SELECTION = "product_selection"
PHASE_PRE_ORDER = "pre_order"
PHASE_COLLECTING = "collecting"
PHASE_SUBMITTED = "submitted"
PHASE_CANCELLED = "cancelled"
ACTIVE_ORDER_PHASES = {PHASE_COLLECTING, PHASE_PRODUCT_SELECTION, PHASE_PRE_ORDER}
