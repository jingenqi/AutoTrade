from pydantic import BaseModel, Field
from typing import Literal
from dataclasses import dataclass

# 基础模型与公共字段可能有用，但此处事件差异很大。
# 我们将单独定义每个事件结构。

# class DealAddEvent(BaseModel):
#     # 当交易执行时（TRADE_TRANSACTION_DEAL_ADD）的模型。
#     event_type: Literal["DEAL_ADD"]
#     ticket: int = Field(..., description="交易单号")
#     order_ticket: int = Field(..., description="导致此交易的订单号")
#     position_id: int = Field(..., description="与此交易关联的头寸单号")
#     magic: int = Field(..., description="智能交易系统魔幻号")
#     symbol: str
#     type: str = Field(..., description="交易类型（例如，'BUY', 'SELL'）")
#     entry: str = Field(..., description="交易入场类型（例如，'IN', 'OUT'）")
#     volume: float = Field(..., gt=0)
#     price: float = Field(..., gt=0)
#     sl: float = Field(ge=0, default=0.0)
#     tp: float = Field(ge=0, default=0.0)
#     commission: float
#     swap: float
#     profit: float
#     comment: str
#     time_msc: int = Field(..., description="交易执行时间戳（毫秒）")

# class OrderEvent(BaseModel):
#     # 订单被添加、更新或移除时的模型。
#     event_type: Literal["ORDER_ADD", "ORDER_UPDATE", "ORDER_DELETE"]
#     ticket: int = Field(..., description="订单号")
#     magic: int
#     symbol: str
#     type: str = Field(..., description="订单类型（例如，'BUY_LIMIT'）")
#     state: str = Field(..., description="订单状态（例如，'PLACED', 'FILLED'）")
#     volume_initial: float = Field(..., ge=0)
#     volume_current: float = Field(..., ge=0)
#     price_open: float = Field(..., ge=0)
#     sl: float = Field(..., ge=0)
#     tp: float = Field(..., ge=0)
#     comment: str
#     time_setup_msc: int = Field(..., description="订单创建时间戳（毫秒）")
#     time_done_msc: int = Field(..., description="订单执行/取消时间戳（毫秒）")

# class PositionModifyEvent(BaseModel):
#     # 头寸被修改时（例如，止损/止盈变更）的模型。
#     event_type: Literal["POSITION_MODIFY"]
#     ticket: int = Field(..., description="头寸单号")
#     magic: int
#     symbol: str
#     type: str = Field(..., description="头寸类型（'BUY' 或 'SELL'）")
#     volume: float = Field(..., gt=0)
#     price_open: float = Field(..., gt=0)
#     sl: float = Field(..., ge=0)
#     tp: float = Field(..., ge=0)
#     price_current: float = Field(..., ge=0)
#     profit: float
#     comment: str
#     time_update_msc: int = Field(..., description="头寸更新时间戳（毫秒）")

# class HeartbeatEvent(BaseModel):
#     # 定义心跳消息的数据契约。
#     type: Literal["HEARTBEAT"]
#     timestamp: int
#     account: int 

# --- 事件定义 ---
# 定义了在系统不同组件之间传递的各种交易事件。
# 这些是数据传输对象 (DTOs)，用于确保事件数据的一致性和结构化。

@dataclass
class BaseEvent:
    # 所有事件的基类。
    event_type: str

@dataclass
class OrderEvent(BaseEvent):
    # 表示 MT5 订单事件。当订单被添加、更新或删除时触发。
    ticket: int
    magic: int
    symbol: str
    type: str
    state: str
    volume_initial: float
    volume_current: float
    price_open: float
    sl: float
    tp: float
    comment: str
    time_setup_msc: int
    time_done_msc: int

    def __post_init__(self):
        self.event_type = "ORDER"

@dataclass
class DealAddEvent(BaseEvent):
    # 表示 MT5 交易事件（交易已完成）。当一笔交易被添加（即订单被执行）时触发。
    ticket: int
    order_ticket: int
    position_id: int
    magic: int
    symbol: str
    type: str
    entry: str
    volume: float
    price: float
    sl: float
    tp: float
    commission: float
    swap: float
    profit: float
    comment: str
    time_msc: int
    
    def __post_init__(self):
        self.event_type = "DEAL_ADD"
        # 添加类型转换和验证
        for field_name, field_type in self.__annotations__.items():
            if field_name == 'event_type': continue
            try:
                current_value = getattr(self, field_name)
                if not isinstance(current_value, field_type):
                    setattr(self, field_name, field_type(current_value))
            except (ValueError, TypeError) as e:
                raise TypeError(f"Field '{field_name}' a '{type(current_value).__name__}' a un type invalide: {e}")

@dataclass
class PositionModifyEvent(BaseEvent):
    # 表示 MT5 头寸修改事件。当现有头寸的 SL/TP 或其他属性被修改时触发。
    ticket: int
    magic: int
    symbol: str
    type: str
    volume: float
    price_open: float
    sl: float
    tp: float
    price_current: float
    profit: float
    comment: str
    time_update_msc: int
    
    def __post_init__(self):
        self.event_type = "POSITION_MODIFY"

@dataclass
class SyncRequestEvent(BaseEvent):
    # 表示来自 MT5 EA 的同步请求事件。用于启动或重新建立与 EA 的连接。
    def __post_init__(self):
        self.event_type = "SYNC_REQUEST"

@dataclass
class GetStateRequestEvent(BaseEvent):
    # 表示从 MT5 EA 获取当前交易状态的请求事件。用于在连接后同步交易状态。
    def __post_init__(self):
        self.event_type = "GET_STATE_REQUEST"

@dataclass
class HeartbeatEvent(BaseEvent):
    # 表示来自 MT5 EA 的心跳事件。用于维持连接，并检测 EA 是否仍然活跃。
    timestamp: int # 以毫秒为单位的时间戳

    def __post_init__(self):
        self.event_type = "HEARTBEAT"


# 事件工厂映射：将事件类型字符串映射到相应的 dataclass。
EVENT_MAPPING = {
    "ORDER_ADD": OrderEvent,
    "ORDER_UPDATE": OrderEvent,
    "ORDER_DELETE": OrderEvent,
    "DEAL_ADD": DealAddEvent,
    "POSITION_MODIFY": PositionModifyEvent,
    "SYNC": SyncRequestEvent,
    "GET_STATE": GetStateRequestEvent,
    "HEARTBEAT": HeartbeatEvent
}

def create_event_from_dict(event_dict: dict) -> BaseEvent:
    # 从字典创建一个事件对象。基于字典中的 'event_type' 字段动态创建正确的事件类型。
    # Args:
    #     event_dict: 包含事件数据的字典。
    # Returns:
    #     BaseEvent 或其子类的实例。
    # Raises:
    #     ValueError: 如果 event_type 未知。
    event_type = event_dict.get("event_type")
    if event_type not in EVENT_MAPPING:
        raise ValueError(f"未知事件类型: {event_type}")
    
    event_class = EVENT_MAPPING[event_type]
    return event_class(**event_dict) 