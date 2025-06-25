from enum import Enum

# MT5 订单类型
class OrderType(Enum):
    BUY = 0
    SELL = 1
    BUY_LIMIT = 2
    SELL_LIMIT = 3
    BUY_STOP = 4
    SELL_STOP = 5
    BUY_STOP_LIMIT = 6
    SELL_STOP_LIMIT = 7

# MT5 交易请求操作类型
class TradeAction(Enum):
    DEAL = 1
    PENDING = 2
    SLTP = 3
    MODIFY = 4
    REMOVE = 5
    CLOSE_BY = 6

# MT5 订单执行类型
class OrderFillingType(Enum):
    FOK = 1
    IOC = 2
    RETURN = 3

# MT5 订单有效期类型
class OrderTimeType(Enum):
    GTC = 0
    DAY = 1
    SPECIFIED = 2
    SPECIFIED_DAY = 3 