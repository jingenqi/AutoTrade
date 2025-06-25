import pytest
from unittest.mock import MagicMock, patch
from multiprocessing import Queue

# Import the functions to be tested
from python.core.worker_process import worker_main, _execute_trade_action, _get_positions_action

# Since worker_main imports mt5, we need to patch it globally for all tests in this file
@pytest.fixture(autouse=True)
def mock_mt5():
    """Mocks the entire MetaTrader5 module."""
    with patch('python.core.worker_process.mt5') as mock:
        # Mock the return object for a successful trade
        mock.order_send.return_value = MagicMock(
            retcode=10009, # TRADE_RETCODE_DONE
            order=67890,
            deal=98765
        )
        # Mock initialization
        mock.initialize.return_value = True
        mock.account_info.return_value = MagicMock(login=12345)
        
        # Mock positions_get to return sample positions
        mock.positions_get.return_value = [
            MagicMock(
                ticket=12345,
                symbol="EURUSD",
                type=0,  # BUY
                volume=0.1,
                price_open=1.1234,
                sl=1.1200,
                tp=1.1300,
                profit=10.5,
                _asdict=lambda: {
                    "ticket": 12345,
                    "symbol": "EURUSD",
                    "type": 0,
                    "volume": 0.1,
                    "price_open": 1.1234,
                    "sl": 1.1200,
                    "tp": 1.1300,
                    "profit": 10.5
                }
            )
        ]
        
        yield mock

@pytest.fixture
def account_config():
    """Provides a sample account configuration."""
    return {
        "name": "TestWorker",
        "login": 12345,
        "terminal_path": "/path/to/mt5terminal.exe"
    }

def test_worker_main_merges_context_with_result(account_config, mock_mt5):
    """
    Tests if the worker_main loop correctly receives a task, executes it,
    and puts a result back that merges the original context with the trade result.
    """
    # 1. Prepare: Create mock queues and a sample task
    task_queue = Queue()
    result_queue = Queue()
    
    task = {
        "action": "execute_trade",
        "payload": {"symbol": "EURUSD", "volume": 0.1},
        "context": {
            "follower_name": "TestWorker",
            "master_ticket": 54321,
            "is_open": True
        }
    }
    shutdown_task = {"action": "SHUTDOWN"}
    
    task_queue.put(task)
    task_queue.put(shutdown_task) # Ensure the worker loop terminates

    # 2. Execute: Run the worker function
    worker_main(account_config, task_queue, result_queue)

    # 3. Assert: Check the contents of the result queue
    assert not result_queue.empty()
    final_result = result_queue.get()
    
    # Check that the original context is preserved
    assert final_result["follower_name"] == "TestWorker"
    assert final_result["master_ticket"] == 54321
    assert final_result["is_open"] is True
    
    # Check that the trade result is included
    assert final_result["status"] == "success"
    assert isinstance(final_result["result"], MagicMock) # The mocked OrderSendResult
    assert final_result["result"].order == 67890

def test_execute_trade_action_success(mock_mt5):
    """
    Tests the _execute_trade_action helper on a successful trade.
    """
    # 1. Prepare: A sample trade request
    request = {"symbol": "EURUSD", "volume": 0.1, "type": "BUY"}
    
    # 2. Execute
    result = _execute_trade_action(request)

    # 3. Assert
    mock_mt5.order_send.assert_called_once_with(request)
    assert result["status"] == "success"
    assert result["result"].retcode == 10009

def test_execute_trade_action_failure(mock_mt5):
    """
    Tests the _execute_trade_action helper on a failed trade.
    """
    # 1. Prepare: Configure the mock to return a failure code
    mock_mt5.order_send.return_value = MagicMock(
        retcode=10013, # TRADE_RETCODE_INVALID_REQUEST
        comment="Invalid request"
    )
    request = {"symbol": "GBPUSD", "volume": 0}

    # 2. Execute
    result = _execute_trade_action(request)

    # 3. Assert
    assert result["status"] == "error"
    assert "Invalid request" in result["message"]
    assert result["result"].retcode == 10013

def test_get_positions_action(mock_mt5):
    """
    Tests the _get_positions_action function to ensure it correctly retrieves position information.
    """
    # 1. Execute: Call the function without a specific ticket
    result = _get_positions_action()
    
    # 2. Assert: Check that positions were retrieved correctly
    assert result["status"] == "success"
    assert isinstance(result["result"], list)
    assert len(result["result"]) == 1
    
    position = result["result"][0]
    assert position["ticket"] == 12345
    assert position["symbol"] == "EURUSD"
    assert position["type"] == 0  # BUY
    assert position["volume"] == 0.1
    assert position["profit"] == 10.5
    
    # 3. Execute again: Call the function with a specific ticket
    mock_mt5.positions_get.reset_mock()
    result_with_ticket = _get_positions_action(ticket=12345)
    
    # 4. Assert: Check that the correct ticket was passed
    mock_mt5.positions_get.assert_called_once_with(ticket=12345)
    assert result_with_ticket["status"] == "success" 