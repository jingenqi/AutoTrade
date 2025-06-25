from dataclasses import dataclass, field, fields
from typing import Dict, Any, Type

@dataclass
class BaseEvent:
    """所有事件的基类。"""
    event_type: str

@dataclass
class OrderEvent(BaseEvent):
    """表示 MT5 订单事件。当订单被添加、更新或删除时触发。"""
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
    time_done_msc: int = 0

@dataclass
class DealAddEvent(BaseEvent):
    """表示 MT5 交易事件（交易已完成）。当一笔交易被添加（即订单被执行）时触发。"""
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
        # 添加类型转换和验证
        for field_info in fields(self):
            field_name = field_info.name
            field_type = field_info.type
            if field_name == 'event_type': continue
            
            current_value = getattr(self, field_name)
            if not isinstance(current_value, field_type):
                try:
                    setattr(self, field_name, field_type(current_value))
                except (ValueError, TypeError) as e:
                    raise TypeError(
                        f"Field '{field_name}' with value '{current_value}' "
                        f"of type '{type(current_value).__name__}' could not be converted to '{field_type.__name__}': {e}"
                    )

@dataclass
class PositionModifyEvent(BaseEvent):
    """表示 MT5 头寸修改事件。当现有头寸的 SL/TP 或其他属性被修改时触发。"""
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

@dataclass
class HeartbeatEvent(BaseEvent):
    """表示来自 MT5 EA 的心跳事件。用于维持连接，并检测 EA 是否仍然活跃。"""
    timestamp: int = field(default_factory=int)
    event_type: str = "HEARTBEAT"


# 事件工厂映射：将事件类型字符串映射到相应的 dataclass。
EVENT_MAPPING: Dict[str, Type[BaseEvent]] = {
    "ORDER_ADD": OrderEvent,
    "ORDER_UPDATE": OrderEvent,
    "ORDER_DELETE": OrderEvent,
    "DEAL_ADD": DealAddEvent,
    "POSITION_MODIFY": PositionModifyEvent,
    "HEARTBEAT": HeartbeatEvent
}

def create_event_from_dict(event_dict: dict) -> BaseEvent:
    """
    从字典创建一个事件对象。基于字典中的 'event_type' 字段动态创建正确的事件类型。
    """
    event_type = event_dict.get("event_type")
    event_class = EVENT_MAPPING.get(event_type)
    
    if not event_class:
        raise ValueError(f"未知事件类型: {event_type}")
    
    # 过滤掉字典中不存在于 dataclass 字段的键
    known_fields = {f.name for f in fields(event_class)}
    filtered_data = {k: v for k, v in event_dict.items() if k in known_fields}
    
    return event_class(**filtered_data)