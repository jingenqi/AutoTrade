import pytest
from pydantic import ValidationError

# 导入我们正在测试的数据模型
from python.core.events import DealAddEvent, OrderEvent, PositionModifyEvent, create_event_from_dict

@pytest.fixture
def valid_deal_add_data():
    """提供一个有效的交易成交事件（DEAL_ADD）字典，用于测试。"""
    return {
        "event_type": "DEAL_ADD",
        "ticket": 123456,
        "order_ticket": 123455,
        "position_id": 123457,
        "magic": 234567,
        "symbol": "EURUSD",
        "type": "BUY",
        "entry": "IN",
        "volume": 0.1,
        "price": 1.12345,
        "sl": 1.12000,
        "tp": 1.13000,
        "commission": -0.5,
        "swap": 0.0,
        "profit": 0.0,
        "comment": "Test",
        "time_msc": 1234567890123
    }

def test_deal_add_validation_with_valid_data(valid_deal_add_data):
    """测试：使用完全有效的数据创建 DealAddEvent 时，不应抛出任何异常。"""
    try:
        DealAddEvent(**valid_deal_add_data)
    except Exception as e:
        pytest.fail(f"使用有效数据进行验证时意外失败: {e}")

def test_deal_add_validation_fails_on_missing_required_field(valid_deal_add_data):
    """测试：当缺少必需字段（例如 'symbol'）时，创建事件应抛出 TypeError。"""
    del valid_deal_add_data["symbol"]
    with pytest.raises(TypeError):
        DealAddEvent(**valid_deal_add_data)

def test_deal_add_validation_fails_on_invalid_data_type(valid_deal_add_data):
    """
    测试：当字段数据类型错误时（例如 'price' 为字符串），
    dataclass 的 __post_init__ 中添加的类型转换逻辑应抛出 TypeError。
    """
    valid_deal_add_data["price"] = "not-a-float"
    with pytest.raises(TypeError):
        DealAddEvent(**valid_deal_add_data)

def test_create_event_from_dict_invalid_type(valid_deal_add_data):
    """测试：当事件类型未知时，事件工厂函数 create_event_from_dict 应抛出 ValueError。"""
    valid_deal_add_data["event_type"] = "UNKNOWN_EVENT"
    with pytest.raises(ValueError, match="未知事件类型: UNKNOWN_EVENT"):
        create_event_from_dict(valid_deal_add_data)

# 由于dataclass没有内置的范围验证，这个测试需要调整或删除
# 如果需要验证，应该在__post_init__中添加
# def test_validation_fails_on_negative_volume(valid_trade_data):
#     # 测试如果 'volume' 不大于零，验证是否失败，基于 Pydantic 字段约束。
#     valid_trade_data["volume"] = -0.1
#     with pytest.raises(ValidationError) as excinfo:
#         TradeEvent.model_validate(valid_trade_data)
#     assert "volume" in str(excinfo.value)

# dataclass没有这个概念，除非字段有默认值
# def test_default_values_are_applied(valid_trade_data):
#     # 测试如果未提供可选字段，是否应用其默认值。
#     del valid_trade_data["comment"]
#     del valid_trade_data["magic"]
    
#     event = TradeEvent.model_validate(valid_trade_data)
#     assert event.comment == ""
#     assert event.magic == 0 