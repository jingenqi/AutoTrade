import pytest
from unittest.mock import Mock, MagicMock, patch, call
import time

# Mock the multiprocessing Queue before importing the class under test
with patch('multiprocessing.Process', MagicMock()):
    with patch('multiprocessing.Queue', MagicMock()):
        from python.core.account_manager import AccountManager

@pytest.fixture
def mock_config_manager():
    """Provides a mock ConfigManager instance."""
    mock = Mock()
    # Mock the method that provides follower configurations
    mock.get_enabled_follower_configs.return_value = {
        "Follower1": {"name": "Follower1", "enabled": True},
        "Follower2": {"name": "Follower2", "enabled": True}
    }
    mock.get_setting.return_value = 12345  # Magic number
    return mock

@pytest.fixture
def account_manager(mock_config_manager):
    """Provides an AccountManager instance with mocked dependencies."""
    # Since we are not testing the process management here,
    # we can disable the start method to avoid side effects.
    with patch.object(AccountManager, 'start', lambda self: None):
        manager = AccountManager(config_manager=mock_config_manager)
        # Manually set up the queues as `start` is mocked
        manager.is_running = True
        manager.task_queues = {
            "Follower1": MagicMock(),
            "Follower2": MagicMock(),
        }
        manager.result_queue = MagicMock()
        yield manager

def test_execute_trades_parallel_sends_correct_task_structure(account_manager):
    """
    Tests if execute_trades_parallel constructs and sends a task
    with the correct structure (payload and context) to the queue.
    """
    # 1. Prepare: Define a trade request
    trade_requests = {
        "Follower1": {
            "symbol": "EURUSD", "volume": 0.1, "type": "BUY",
            "master_ticket": 12345, "is_open": True,
            "is_close": False, "is_pending": False,
        }
    }

    # 2. Execute: Call the method to be tested
    account_manager.execute_trades_parallel(trade_requests)

    # 3. Assert: Check if the queue's put method was called with the correct data
    follower1_queue = account_manager.task_queues["Follower1"]
    follower1_queue.put.assert_called_once()
    
    # Inspect the argument passed to put()
    call_args = follower1_queue.put.call_args[0][0]
    
    # Check the overall structure
    assert "action" in call_args
    assert call_args["action"] == "execute_trade"
    assert "payload" in call_args
    assert "context" in call_args
    
    # Check the context details
    context = call_args["context"]
    assert context["follower_name"] == "Follower1"
    assert context["master_ticket"] == 12345
    assert context["is_open"] is True
    assert context["is_close"] is False
    assert context["is_pending"] is False
    
    # Check that the other queue was not used
    account_manager.task_queues["Follower2"].put.assert_not_called()

def test_register_trade_callback(account_manager):
    """
    Tests if the trade callback registration works correctly and 
    if the callback is invoked with the right parameters.
    """
    # 1. Prepare: Create a mock callback function
    mock_callback = Mock()
    
    # 2. Execute: Register the callback
    account_manager.register_trade_callback(mock_callback)
    
    # 3. Assert: Check if the callback was stored
    assert account_manager._trade_callback == mock_callback
    
    # 4. Execute: Simulate receiving a trade result
    test_result = {"status": "success", "follower_name": "Follower1"}
    account_manager._trade_callback(test_result)
    
    # 5. Assert: Check if the callback was called with the result
    mock_callback.assert_called_once_with(test_result)

def test_get_account_info_synchronous(account_manager):
    """
    Tests the synchronous account info retrieval method.
    """
    # 1. Prepare: Mock the _send_request_and_wait method
    expected_result = {"balance": 10000, "equity": 10050}
    account_manager._send_request_and_wait = Mock(return_value={"status": "success", "result": expected_result})
    
    # 2. Execute: Call the get_account_info method
    result = account_manager.get_account_info("Follower1")
    
    # 3. Assert: Check if _send_request_and_wait was called with correct parameters
    account_manager._send_request_and_wait.assert_called_once_with(
        "Follower1", {"action": "get_account_info"}
    )
    
    # 4. Assert: Check if the result is correct
    assert result == expected_result

def test_get_positions_synchronous(account_manager):
    """
    Tests the synchronous positions retrieval method.
    """
    # 1. Prepare: Mock the _send_request_and_wait method
    expected_positions = [{"ticket": 12345, "symbol": "EURUSD", "volume": 0.1}]
    account_manager._send_request_and_wait = Mock(
        return_value={"status": "success", "result": expected_positions}
    )
    
    # 2. Execute: Call the get_positions method without a ticket
    result = account_manager.get_positions("Follower1")
    
    # 3. Assert: Check if _send_request_and_wait was called with correct parameters
    account_manager._send_request_and_wait.assert_called_once_with(
        "Follower1", {"action": "get_positions", "ticket": None}
    )
    
    # 4. Assert: Check if the result is correct
    assert result == expected_positions
    
    # 5. Reset the mock and test with a specific ticket
    account_manager._send_request_and_wait.reset_mock()
    account_manager.get_positions("Follower1", ticket=12345)
    
    # 6. Assert: Check if the ticket parameter was passed correctly
    account_manager._send_request_and_wait.assert_called_once_with(
        "Follower1", {"action": "get_positions", "ticket": 12345}
    )

def test_get_all_follower_info(account_manager):
    """
    Tests the get_all_follower_info method that retrieves account info for all followers.
    """
    # 1. Prepare: Mock the Queue and its get method to return different results
    mock_reply_queue = MagicMock()
    
    # Set up the queue to return two results and then raise Empty
    mock_reply_queue.get.side_effect = [
        {"account_name": "Follower1", "status": "success", "result": {"balance": 10000}},
        {"account_name": "Follower2", "status": "success", "result": {"balance": 20000}}
    ]
    
    # Patch Queue creation
    with patch('python.core.account_manager.Queue', return_value=mock_reply_queue):
        # 2. Execute: Call the method
        results = account_manager.get_all_follower_info()
        
        # 3. Assert: Check if the task queues were used correctly
        account_manager.task_queues["Follower1"].put.assert_called_once()
        account_manager.task_queues["Follower2"].put.assert_called_once()
        
        # 4. Assert: Check if the results were collected correctly
        assert len(results) == 2
        assert results["Follower1"]["balance"] == 10000
        assert results["Follower2"]["balance"] == 20000 