# Add project root to sys.path to allow imports from parent directories
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import pytest
from pydantic import ValidationError

# Import the data model we are testing
from mt5_copier.python.core.events import TradeEvent

@pytest.fixture
def valid_trade_data():
    """Provides a valid dictionary for a trade event."""
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
    """
    Tests that the TradeEvent model successfully validates a correct data structure.
    """
    try:
        TradeEvent.model_validate(valid_trade_data)
    except ValidationError as e:
        pytest.fail(f"Validation failed unexpectedly for valid data: {e}")

def test_validation_fails_on_missing_required_field(valid_trade_data):
    """
    Tests that validation fails if a required field (e.g., 'symbol') is missing.
    """
    del valid_trade_data["symbol"]
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    # Check that the error message mentions the missing field
    assert "symbol" in str(excinfo.value)

def test_validation_fails_on_invalid_data_type(valid_trade_data):
    """
    Tests that validation fails if a field has the wrong data type (e.g., 'price' as string).
    """
    valid_trade_data["price"] = "not-a-float"
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    assert "price" in str(excinfo.value)

def test_validation_fails_on_negative_volume(valid_trade_data):
    """
    Tests that validation fails if 'volume' is not greater than zero,
    based on the Pydantic Field constraint.
    """
    valid_trade_data["volume"] = -0.1
    with pytest.raises(ValidationError) as excinfo:
        TradeEvent.model_validate(valid_trade_data)
    assert "volume" in str(excinfo.value)

def test_default_values_are_applied(valid_trade_data):
    """
    Tests that optional fields get their default values if not provided.
    """
    del valid_trade_data["comment"]
    del valid_trade_data["magic"]
    
    event = TradeEvent.model_validate(valid_trade_data)
    assert event.comment == ""
    assert event.magic == 0 