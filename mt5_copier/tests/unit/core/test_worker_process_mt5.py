"""
Tests for worker_process.py that involve actual MT5 API calls.
These tests are skipped if MT5 is not available.
"""

import pytest
import os
import sys
import time
from multiprocessing import Queue
from unittest.mock import MagicMock

# Try to import MT5 to check if it's available
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

# Import the functions to be tested
from python.core.worker_process import worker_main, _execute_trade_action, _get_positions_action

# Skip all tests in this module if MT5 is not available
pytestmark = pytest.mark.skipif(not MT5_AVAILABLE, reason="MetaTrader5 module not available")

@pytest.fixture
def account_config():
    """Provides a sample account configuration."""
    # This should be configured with a valid MT5 terminal path for testing
    # We'll use an environment variable to avoid hardcoding paths
    terminal_path = os.environ.get("MT5_TERMINAL_PATH", "")
    
    return {
        "name": "TestWorker",
        "login": int(os.environ.get("MT5_LOGIN", "0")),
        "terminal_path": terminal_path
    }

@pytest.mark.skipif(not os.environ.get("MT5_TERMINAL_PATH"), 
                   reason="MT5_TERMINAL_PATH environment variable not set")
def test_worker_initialization(account_config):
    """
    Tests if the worker can initialize a connection to MT5.
    This test requires a running MT5 terminal.
    """
    # Set up queues
    task_queue = Queue()
    result_queue = Queue()
    
    # Add a shutdown task to ensure the worker terminates
    task_queue.put({"action": "SHUTDOWN"})
    
    # Start the worker in the current process (not ideal but simpler for testing)
    worker_main(account_config, task_queue, result_queue)
    
    # If we got here without exceptions, the worker initialized successfully
    assert True

@pytest.mark.skipif(not os.environ.get("MT5_TERMINAL_PATH"), 
                   reason="MT5_TERMINAL_PATH environment variable not set")
def test_get_account_info_action(account_config):
    """
    Tests the get_account_info_action with a real MT5 connection.
    """
    # Set up queues
    task_queue = Queue()
    result_queue = Queue()
    
    # Add a get_account_info task
    task_queue.put({"action": "get_account_info"})
    
    # Add a shutdown task to ensure the worker terminates
    task_queue.put({"action": "SHUTDOWN"})
    
    # Start the worker
    worker_main(account_config, task_queue, result_queue)
    
    # Get the result
    result = result_queue.get()
    
    # Check if we got a valid result
    assert result["status"] == "success"
    assert "result" in result
    assert "login" in result["result"]
    assert result["result"]["login"] == account_config["login"]

@pytest.mark.skipif(not os.environ.get("MT5_TERMINAL_PATH"), 
                   reason="MT5_TERMINAL_PATH environment variable not set")
def test_get_positions_action_with_real_mt5():
    """
    Tests the _get_positions_action function with a real MT5 connection.
    """
    # Initialize MT5 directly for this test
    terminal_path = os.environ.get("MT5_TERMINAL_PATH", "")
    if not terminal_path or not mt5.initialize(path=terminal_path):
        pytest.skip("Failed to initialize MT5")
    
    try:
        # Call the function
        result = _get_positions_action()
        
        # Check the result structure
        assert "status" in result
        assert result["status"] == "success"
        assert "result" in result
        assert isinstance(result["result"], list)
        
        # Test with a specific ticket (that likely doesn't exist)
        result_with_ticket = _get_positions_action(ticket=999999)
        assert result_with_ticket["status"] == "success"
        assert isinstance(result_with_ticket["result"], list)
        
    finally:
        # Clean up
        mt5.shutdown()

@pytest.mark.skipif(True, reason="This test would execute real trades and is disabled by default")
def test_execute_trade_action_with_real_mt5():
    """
    Tests the _execute_trade_action function with a real MT5 connection.
    WARNING: This would execute actual trades and is disabled by default.
    Only enable this for testing in a demo account with proper configuration.
    """
    # Initialize MT5 directly for this test
    terminal_path = os.environ.get("MT5_TERMINAL_PATH", "")
    if not terminal_path or not mt5.initialize(path=terminal_path):
        pytest.skip("Failed to initialize MT5")
    
    try:
        # Create a minimal buy request for a small volume
        symbol = "EURUSD"
        
        # Check if the symbol is available
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            pytest.skip(f"Symbol {symbol} not available")
        
        # Enable the symbol if needed
        if not symbol_info.visible:
            mt5.symbol_select(symbol, True)
        
        # Create a market buy request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": symbol_info.volume_min,
            "type": mt5.ORDER_TYPE_BUY,
            "price": mt5.symbol_info_tick(symbol).ask,
            "deviation": 10,
            "magic": 12345,
            "comment": "pytest_test",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        # Execute the trade
        result = _execute_trade_action(request)
        
        # Check the result
        assert result["status"] == "success"
        assert "result" in result
        assert result["result"].retcode == mt5.TRADE_RETCODE_DONE
        
        # Clean up - close the position we just opened
        positions = mt5.positions_get(symbol=symbol)
        if positions:
            for position in positions:
                if position.magic == 12345 and position.comment == "pytest_test":
                    close_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": position.volume,
                        "type": mt5.ORDER_TYPE_SELL if position.type == 0 else mt5.ORDER_TYPE_BUY,
                        "position": position.ticket,
                        "price": mt5.symbol_info_tick(symbol).bid if position.type == 0 else mt5.symbol_info_tick(symbol).ask,
                        "deviation": 10,
                        "magic": 12345,
                        "comment": "pytest_close",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    mt5.order_send(close_request)
                    
    finally:
        # Clean up
        mt5.shutdown() 