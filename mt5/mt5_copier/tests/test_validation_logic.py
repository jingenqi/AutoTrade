# 将项目根目录添加到 sys.path 中，以允许从父目录导入
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pytest
from pydantic import ValidationError

# 导入我们正在测试的数据模型
from mt5_copier.python.core.events import TradeEvent

@pytest.fixture
def valid_trade_data():
    # 为交易事件提供一个有效的字典。
    return {
        "event_type": "TRADE_TRANSACTION_DEAL_ADD",
        "order_id": 12345,
        "position_id": 54321,
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": 0.1,
        "price": 1.12345,
        "sl": 1.12000,
        "tp": 1.13000,
        "magic": 999,
        "comment": "Valid test",
        "timestamp_msc": 1678886400000
    }

def test_validation_with_valid_data(valid_trade_data):
    # 测试 TradeEvent 模型是否成功验证了正确的数据结构。
    try:
        TradeEvent.model_validate(valid_trade_data)
    except ValidationError as e:
        pytest.fail(f"对有效数据进行验证时意外失败: {e}")

def test_validation_fails_on_missing_required_field(valid_trade_data):
    # 测试如果缺少必需字段（例如 'symbol'），验证是否失败。
    del valid_trade_data["symbol"]
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    # 检查错误消息是否提及了缺失的字段
    assert "symbol" in str(excinfo.value)

def test_validation_fails_on_invalid_data_type(valid_trade_data):
    # 测试如果字段数据类型错误（例如 'price' 为字符串），验证是否失败。
    valid_trade_data["price"] = "not-a-float"
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    assert "price" in str(excinfo.value)

def test_validation_fails_on_negative_volume(valid_trade_data):
    # 测试如果 'volume' 不大于零，验证是否失败，基于 Pydantic 字段约束。
    valid_trade_data["volume"] = -0.1
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    assert "volume" in str(excinfo.value)

def test_default_values_are_applied(valid_trade_data):
    # 测试如果未提供可选字段，是否应用其默认值。
    del valid_trade_data["comment"]
    del valid_trade_data["magic"]
    
    event = TradeEvent.model_validate(valid_trade_data)
    assert event.comment == ""
    assert event.magic == 0 