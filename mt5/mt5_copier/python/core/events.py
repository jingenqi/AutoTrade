from pydantic import BaseModel, Field
from typing import Literal

class TradeEvent(BaseModel):
    """
    Defines the data contract for a trade event message.
    This model is used for validation to ensure data integrity between the
    MQL5 EA and the Python controller.
    """
    event_type: str
    order_id: int
    position_id: int
    symbol: str
    action: str  # e.g., "BUY", "SELL", "SELL_LIMIT", etc.
    volume: float = Field(gt=0, description="Trade volume must be positive")
    price: float = Field(gt=0, description="Trade price must be positive")
    sl: float = Field(ge=0, default=0.0)
    tp: float = Field(ge=0, default=0.0)
    magic: int = Field(ge=0, default=0)
    comment: str = Field(default="")
    timestamp_msc: int

class HeartbeatEvent(BaseModel):
    """
    Defines the data contract for a heartbeat message.
    """
    type: Literal["HEARTBEAT"]
    timestamp: int
    account: int 