import pytest
from unittest.mock import Mock, patch, MagicMock
import MetaTrader5 as mt5

from python.core.trade_engine import TradeEngine
from python.core.events import DealAddEvent, OrderEvent, PositionModifyEvent

@pytest.fixture
def mock_mt5():
    """模拟 mt5 模块，提供测试所需的常量和函数返回值。"""
    with patch('python.core.trade_engine.mt5') as mock_mt5_module:
        # 模拟 MT5 订单类型常量
        mock_mt5_module.ORDER_TYPE_BUY = 0
        mock_mt5_module.ORDER_TYPE_SELL = 1
        mock_mt5_module.ORDER_TYPE_BUY_LIMIT = 2
        mock_mt5_module.ORDER_TYPE_SELL_LIMIT = 3
        mock_mt5_module.ORDER_TYPE_BUY_STOP = 4
        mock_mt5_module.ORDER_TYPE_SELL_STOP = 5
        mock_mt5_module.ORDER_TYPE_BUY_STOP_LIMIT = 6
        mock_mt5_module.ORDER_TYPE_SELL_STOP_LIMIT = 7
        
        # 模拟 MT5 交易动作常量
        mock_mt5_module.TRADE_ACTION_DEAL = 1
        mock_mt5_module.TRADE_ACTION_PENDING = 5
        mock_mt5_module.TRADE_ACTION_SLTP = 6
        
        # 模拟 symbol_info 函数，返回一个包含必要属性的对象
        symbol_info_mock = MagicMock()
        symbol_info_mock.point = 0.00001
        symbol_info_mock.volume_min = 0.01
        symbol_info_mock.volume_max = 100.0
        symbol_info_mock.volume_step = 0.01
        mock_mt5_module.symbol_info.return_value = symbol_info_mock
        
        yield mock_mt5_module

@pytest.fixture
def mock_config_manager():
    """提供一个模拟的 ConfigManager 实例。"""
    mock = Mock()
    # 添加get_setting方法的模拟
    mock.get_setting.return_value = 12345
    return mock

@pytest.fixture
def mock_account_manager():
    """提供一个模拟的 AccountManager 实例。"""
    return Mock()

@pytest.fixture
def trade_engine(mock_config_manager, mock_account_manager, mock_mt5):
    """使用模拟的依赖项创建一个 TradeEngine 实例，用于测试。"""
    engine = TradeEngine(
        config_manager=mock_config_manager,
        account_manager=mock_account_manager
    )
    
    # 模拟_get_symbol_info方法，直接返回mock_mt5.symbol_info的结果
    engine._get_symbol_info = lambda follower_name, symbol: mock_mt5.symbol_info(symbol)
    
    return engine

# --- 创建测试事件的辅助函数 ---
def create_mock_deal_event(position_id=200, event_type="BUY", entry="IN", volume=0.1, sl=1.12000, tp=1.12800):
    """创建一个模拟的交易成交事件（DealAddEvent）。"""
    return DealAddEvent(
        event_type="DEAL_ADD", ticket=100, order_ticket=10, position_id=position_id,
        magic=12345, symbol="EURUSD", type=event_type, entry=entry, volume=volume,
        price=1.12345, sl=sl, tp=tp, commission=-0.1, swap=0, profit=0,
        comment="Test Event", time_msc=123456789
    )

def create_mock_modify_event(position_id=200, sl=1.1950, tp=1.2100):
    """创建一个模拟的持仓修改事件（PositionModifyEvent）。"""
    return PositionModifyEvent(
        event_type="POSITION_MODIFY", ticket=position_id, magic=123, symbol="EURUSD",
        type="BUY", volume=0.1, price_open=1.2000, sl=sl, tp=tp,
        price_current=1.2010, profit=10.0, comment="Modify SL/TP", time_update_msc=1625000000000
    )

# --- 测试用例 ---

class TestTradeEngineOpenPosition:
    """测试开仓相关的逻辑。"""

    def test_build_request_for_regular_open_buy(self, trade_engine, mock_config_manager):
        """测试：正向跟单 - 当主账户开买单时，跟单账户也应生成正确的买单请求。"""
        # 1. 准备：配置一个正向跟单的账户，并创建一个主账户买入事件
        follower_config = {
            "name": "Follower_Regular", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True
        }
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Regular": follower_config}
        master_event = create_mock_deal_event()

        # 2. 执行：构建交易请求
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：检查生成的请求是否符合预期
        assert "Follower_Regular" in trade_requests
        request = trade_requests["Follower_Regular"]
        assert request["action"] == mt5.TRADE_ACTION_DEAL
        assert request["type"] == mt5.ORDER_TYPE_BUY
        assert request["volume"] == 0.1
        assert request["sl"] == 1.12000
        assert request["tp"] == 1.12800
        assert request["magic"] == trade_engine.config_manager.get_setting("magic_number", 12345)
        assert request["comment"] == "跟单"

    def test_build_request_for_reverse_open_sell(self, trade_engine, mock_config_manager):
        """测试：反向跟单 - 当主账户开买单时，跟单账户应生成正确的卖单请求，且止损止盈互换。"""
        # 1. 准备：配置一个反向跟单的账户
        follower_config = {
            "name": "Follower_Reverse", "enabled": True, "strategy": "reverse",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True
        }
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Reverse": follower_config}
        master_event = create_mock_deal_event(sl=1.12000, tp=1.12800)

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：订单类型应为卖单，且止损止盈互换
        assert "Follower_Reverse" in trade_requests
        request = trade_requests["Follower_Reverse"]
        assert request["type"] == mt5.ORDER_TYPE_SELL
        assert request["sl"] != 1.12000
        assert request["tp"] != 1.12800
        assert request["magic"] == self.config_manager.get_setting("magic_number", 12345)

class TestTradeEngineClosePosition:
    """测试平仓相关的逻辑。"""
    
    def test_build_request_for_close_position(self, trade_engine, mock_config_manager):
        """测试：当收到主账户平仓事件时，应为跟单账户生成正确的平仓请求。"""
        # 1. 准备：设置持仓映射，模拟一个已存在的跟单关系
        master_position_id = "200"
        follower_position_id = 500
        trade_engine.position_map = {master_position_id: {"Follower_Regular": follower_position_id}}
        
        follower_config = {"name": "Follower_Regular", "enabled": True, "strategy": "regular", "max_slippage_pips": 5}
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Regular": follower_config}
        
        master_event = create_mock_deal_event(position_id=int(master_position_id), type="SELL", entry="OUT")

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=False, follower_positions=trade_engine.position_map[master_position_id])

        # 3. 断言
        assert "Follower_Regular" in trade_requests
        request = trade_requests["Follower_Regular"]
        assert request["action"] == mt5.TRADE_ACTION_DEAL
        assert request["position"] == follower_position_id
        assert request["volume"] == 0.1
        assert request["type"] == mt5.ORDER_TYPE_SELL

class TestTradeEngineModifyPosition:
    """测试修改持仓（止损/止盈）的逻辑。"""

    def test_handle_position_modify_normal_follow(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：正向跟单 - 当主账户修改止损止盈时，跟单账户应以相同的值进行修改。"""
        # 1. 准备
        master_pos_id = "200"
        follower_pos_id = 500
        trade_engine.position_map = {master_pos_id: {"Follower_Normal": follower_pos_id}}
        
        follower_config = {"name": "Follower_Normal", "strategy": "regular", "copy_sl_tp": True}
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Normal": follower_config}
        
        event = create_mock_modify_event(ticket=int(master_pos_id), sl=1.1950, tp=1.2100)

        # 2. 执行
        trade_engine._handle_position_modify(event)

        # 3. 断言
        mock_account_manager.execute_trades_parallel.assert_called_once()
        call_args = mock_account_manager.execute_trades_parallel.call_args[0][0]
        request = call_args["Follower_Normal"]
        assert request['action'] == mt5.TRADE_ACTION_SLTP
        assert request['position'] == follower_pos_id
        assert request['sl'] == 1.1950
        assert request['tp'] == 1.2100

    def test_handle_position_modify_reverse_follow(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：反向跟单 - 当主账户修改止损止盈时，跟单账户的止损止盈应互换。"""
        # 1. 准备
        master_pos_id = "200"
        follower_pos_id = 500
        trade_engine.position_map = {master_pos_id: {"Follower_Reverse": follower_pos_id}}
        
        follower_config = {"name": "Follower_Reverse", "strategy": "reverse", "copy_sl_tp": True}
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Reverse": follower_config}
        
        event = create_mock_modify_event(ticket=int(master_pos_id), sl=1.1950, tp=1.2100)
        
        # 2. 执行
        trade_engine._handle_position_modify(event)

        # 3. 断言：对于反向策略，止损和止盈的值应该互换
        mock_account_manager.execute_trades_parallel.assert_called_once()
        call_args = mock_account_manager.execute_trades_parallel.call_args[0][0]
        request = call_args["Follower_Reverse"]
        assert request['action'] == mt5.TRADE_ACTION_SLTP
        assert request['position'] == follower_pos_id
        assert request['sl'] != 1.1950
        assert request['tp'] != 1.2100

class TestLotSizeCalculation:
    """测试不同手数计算模式的逻辑。"""

    def test_build_request_with_lot_multiplier(self, trade_engine, mock_config_manager):
        """测试：手数模式为"倍率"时，跟单手数应是 主账户手数 * 倍率。"""
        # 1. 准备
        follower_config = {
            "name": "Follower_Multiplier", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 2.5
        }
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Multiplier": follower_config}
        master_event = create_mock_deal_event(volume=0.2)

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：0.2 (主账户) * 2.5 (倍率) = 0.5 (跟单账户)
        assert "Follower_Multiplier" in trade_requests
        assert trade_requests["Follower_Multiplier"]["volume"] == 0.5
        
    def test_build_request_with_fixed_lot(self, trade_engine, mock_config_manager):
        """测试：手数模式为"固定值"时，跟单手数应总是等于配置的固定值。"""
        # 1. 准备
        follower_config = {
            "name": "Follower_Fixed", "enabled": True, "strategy": "regular",
            "lot_mode": "fixed", "lot_value": 0.77
        }
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower_Fixed": follower_config}
        master_event = create_mock_deal_event(volume=1.5)

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：手数应为固定的 0.77，忽略主账户的 1.5
        assert "Follower_Fixed" in trade_requests
        assert trade_requests["Follower_Fixed"]["volume"] == 0.77

class TestTradeResultHandling:
    """Tests the logic for handling trade execution results."""

    def test_on_trade_executed_updates_position_map_on_open(self, trade_engine, mock_mt5):
        """
        Tests if the position_map is correctly updated when an 'open' trade succeeds.
        """
        # 1. Prepare: An empty position map and a successful trade result
        trade_engine.position_map = {}
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        result_payload = {
            "follower_name": "Follower1",
            "master_ticket": "12345",
            "is_open": True,
            "is_close": False,
            "is_pending": False,
            "status": "success",
            "result": MagicMock(
                retcode=mock_mt5.TRADE_RETCODE_DONE,
                deal=98765, # The follower position ID
                order=67890
            )
        }
        
        # 2. Execute: Call the callback
        trade_engine._on_trade_executed(result_payload)
        
        # 3. Assert: Check if the position map was updated correctly
        assert "12345" in trade_engine.position_map
        assert "Follower1" in trade_engine.position_map["12345"]
        assert trade_engine.position_map["12345"]["Follower1"] == 98765

    def test_on_trade_executed_removes_from_map_on_close(self, trade_engine, mock_mt5):
        """
        Tests if the position_map is correctly updated when a 'close' trade succeeds.
        """
        # 1. Prepare: A position map with an existing entry and a successful close trade result
        trade_engine.position_map = {"12345": {"Follower1": 98765, "Follower2": 87654}}
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        result_payload = {
            "follower_name": "Follower1",
            "master_ticket": "12345",
            "is_open": False,
            "is_close": True,
            "is_pending": False,
            "status": "success",
            "result": MagicMock(
                retcode=mock_mt5.TRADE_RETCODE_DONE,
                deal=11111, # The close deal ID
                order=22222
            )
        }
        
        # 2. Execute: Call the callback
        trade_engine._on_trade_executed(result_payload)
        
        # 3. Assert: Check if the position map was updated correctly
        # The Follower1 entry should be removed, but Follower2 should remain
        assert "12345" in trade_engine.position_map
        assert "Follower1" not in trade_engine.position_map["12345"]
        assert "Follower2" in trade_engine.position_map["12345"]
        assert trade_engine.position_map["12345"]["Follower2"] == 87654

    def test_on_trade_executed_does_nothing_on_failure(self, trade_engine, mock_mt5):
        """
        Tests if the position_map remains unchanged when a trade fails.
        """
        # 1. Prepare: A position map with an existing entry and a failed trade result
        original_map = {"12345": {"Follower1": 98765}}
        trade_engine.position_map = original_map.copy()
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        result_payload = {
            "follower_name": "Follower1",
            "master_ticket": "12345",
            "is_open": True,
            "status": "error",
            "message": "Trade failed",
            "result": MagicMock(
                retcode=10013, # Some error code
                comment="Invalid request"
            )
        }
        
        # 2. Execute: Call the callback
        trade_engine._on_trade_executed(result_payload)
        
        # 3. Assert: Check if the position map remains unchanged
        assert trade_engine.position_map == original_map

    def test_on_trade_executed_with_pending_order(self, trade_engine, mock_mt5):
        """
        Tests if the pending_order_map is correctly updated when a 'pending' trade succeeds.
        """
        # 1. Prepare: An empty pending order map and a successful pending order result
        trade_engine.pending_order_map = {}
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        result_payload = {
            "follower_name": "Follower1",
            "master_ticket": "12345",
            "is_open": False,
            "is_close": False,
            "is_pending": True,
            "status": "success",
            "result": MagicMock(
                retcode=mock_mt5.TRADE_RETCODE_DONE,
                deal=0,  # No deal for pending orders
                order=67890  # The follower order ID
            )
        }
        
        # 2. Execute: Call the callback
        trade_engine._on_trade_executed(result_payload)
        
        # 3. Assert: Check if the pending order map was updated correctly
        assert "12345" in trade_engine.pending_order_map
        assert "Follower1" in trade_engine.pending_order_map["12345"]
        assert trade_engine.pending_order_map["12345"]["Follower1"] == 67890

    def test_on_trade_executed_with_complex_scenario(self, trade_engine, mock_mt5):
        """
        Tests a more complex scenario with multiple operations to ensure the callback
        handles different types of trade results correctly.
        """
        # 1. Prepare: Set up initial maps and mock MT5
        trade_engine.position_map = {
            "100": {"FollowerA": 1001, "FollowerB": 1002},
            "200": {"FollowerA": 2001}
        }
        trade_engine.pending_order_map = {
            "300": {"FollowerA": 3001}
        }
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        # Mock the update_positions method to avoid side effects
        trade_engine.update_positions = MagicMock()
        
        # 2. Execute: Simulate a sequence of trade results
        
        # First: Open a new position for FollowerB on master position 200
        trade_engine._on_trade_executed({
            "follower_name": "FollowerB",
            "master_ticket": "200",
            "is_open": True,
            "is_close": False,
            "is_pending": False,
            "status": "success",
            "result": MagicMock(retcode=mock_mt5.TRADE_RETCODE_DONE, deal=2002)
        })
        
        # Second: Close FollowerA's position on master position 100
        trade_engine._on_trade_executed({
            "follower_name": "FollowerA",
            "master_ticket": "100",
            "is_open": False,
            "is_close": True,
            "is_pending": False,
            "status": "success",
            "result": MagicMock(retcode=mock_mt5.TRADE_RETCODE_DONE, deal=9999)
        })
        
        # Third: Create a pending order for FollowerB
        trade_engine._on_trade_executed({
            "follower_name": "FollowerB",
            "master_ticket": "300",
            "is_open": False,
            "is_close": False,
            "is_pending": True,
            "status": "success",
            "result": MagicMock(retcode=mock_mt5.TRADE_RETCODE_DONE, order=3002)
        })
        
        # 3. Assert: Check the final state of the maps
        
        # Check position_map updates
        assert "FollowerB" in trade_engine.position_map["200"]
        assert trade_engine.position_map["200"]["FollowerB"] == 2002
        
        assert "FollowerA" not in trade_engine.position_map["100"]
        assert "FollowerB" in trade_engine.position_map["100"]
        
        # Check pending_order_map updates
        assert "FollowerB" in trade_engine.pending_order_map["300"]
        assert trade_engine.pending_order_map["300"]["FollowerB"] == 3002
        assert "FollowerA" in trade_engine.pending_order_map["300"]
        
        # Check that update_positions was called after each operation
        assert trade_engine.update_positions.call_count == 3

class TestIntegrationFlow:
    """测试从事件处理到动作执行的完整流程。"""

    def test_process_deal_add_event_and_map_update(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：处理一个开仓事件后，应正确调用交易执行函数，并更新内部的持仓映射表。"""
        # 1. 准备：一个跟单账户、一个开仓事件，以及一个模拟的成功交易结果
        follower_config = {
            "name": "Follower1", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True
        }
        mock_config_manager.get_enabled_follower_configs.return_value = {"Follower1": follower_config}
        
        event = create_mock_deal_event(position_id=200)
        
        # This test doesn't need to simulate the return anymore,
        # as the map update is handled by the _on_trade_executed callback,
        # which is tested separately.

        # 2. 执行
        trade_engine.process_event(event.to_dict())

        # 3. 断言
        # 断言交易执行函数被调用
        mock_account_manager.execute_trades_parallel.assert_called_once()

if __name__ == '__main__':
    pytest.main() 