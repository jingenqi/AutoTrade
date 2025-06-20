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
        
        # 模拟 symbol_info 函数，返回一个包含 point 的对象
        mock_mt5_module.symbol_info.return_value = MagicMock(point=0.00001)
        yield mock_mt5_module

@pytest.fixture
def mock_config_manager():
    """提供一个模拟的 ConfigManager 实例。"""
    return Mock()

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
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True, "magic": 11111
        }
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        master_event = create_mock_deal_event()

        # 2. 执行：构建交易请求
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：检查生成的请求是否符合预期
        assert "Follower_Regular" in trade_requests
        request = trade_requests["Follower_Regular"]
        assert request["action"] == 1  # 交易类型应为 DEAL
        assert request["type"] == 0    # 订单类型应为 BUY
        assert request["volume"] == 0.1
        assert request["sl"] == 1.12000
        assert request["tp"] == 1.12800
        assert request["magic"] == 11111
        assert request["comment"] == "MasterPos:200"

    def test_build_request_for_reverse_open_sell(self, trade_engine, mock_config_manager):
        """测试：反向跟单 - 当主账户开买单时，跟单账户应生成正确的卖单请求，且止损止盈互换。"""
        # 1. 准备：配置一个反向跟单的账户
        follower_config = {
            "name": "Follower_Reverse", "enabled": True, "strategy": "reverse",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True, "magic": 22222
        }
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        master_event = create_mock_deal_event(sl=1.12000, tp=1.12800)

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：订单类型应为卖单，且止损止盈互换
        assert "Follower_Reverse" in trade_requests
        request = trade_requests["Follower_Reverse"]
        assert request["type"] == 1          # 订单类型应为 SELL
        assert request["sl"] == 1.12800      # 止损应为主账户的止盈
        assert request["tp"] == 1.12000      # 止盈应为主账户的止损
        assert request["magic"] == 22222

class TestTradeEngineClosePosition:
    """测试平仓相关的逻辑。"""
    
    def test_build_request_for_close_position(self, trade_engine, mock_config_manager):
        """测试：当收到主账户平仓事件时，应为跟单账户生成正确的平仓请求。"""
        # 1. 准备：设置持仓映射，模拟一个已存在的跟单关系
        master_position_id = 200
        follower_position_id = 500
        trade_engine.position_map = {master_position_id: {"Follower_Regular": {"position_id": follower_position_id}}}
        follower_config = {"name": "Follower_Regular", "enabled": True, "strategy": "regular"}
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        master_event = create_mock_deal_event(position_id=master_position_id, event_type="SELL", entry="OUT")

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=False, follower_positions=trade_engine.position_map[master_position_id])

        # 3. 断言
        assert "Follower_Regular" in trade_requests
        request = trade_requests["Follower_Regular"]
        assert request["action"] == 1  # 交易类型应为 DEAL
        assert request["position"] == follower_position_id  # 必须正确地指定要平掉的跟单账户持仓号
        assert request["volume"] == 0.1

class TestTradeEngineModifyPosition:
    """测试修改持仓（止损/止盈）的逻辑。"""

    def test_handle_position_modify_normal_follow(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：正向跟单 - 当主账户修改止损止盈时，跟单账户应以相同的值进行修改。"""
        # 1. 准备
        master_pos_id = 200
        follower_pos_id = 500
        trade_engine.position_map = {master_pos_id: {"Follower_Normal": {"position_id": follower_pos_id}}}
        
        follower_config = {"name": "Follower_Normal", "strategy": "regular", "copy_sl_tp": True}
        mock_config_manager.get_follower_config.return_value = follower_config
        
        event = create_mock_modify_event(position_id=master_pos_id, sl=1.1950, tp=1.2100)

        # 2. 执行
        trade_engine._handle_position_modify(event)

        # 3. 断言
        mock_account_manager.modify_position.assert_called_once_with("Follower_Normal", follower_pos_id, 1.1950, 1.2100)

    def test_handle_position_modify_reverse_follow(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：反向跟单 - 当主账户修改止损止盈时，跟单账户的止损止盈应互换。"""
        # 1. 准备
        master_pos_id = 200
        follower_pos_id = 500
        trade_engine.position_map = {master_pos_id: {"Follower_Reverse": {"position_id": follower_pos_id}}}
        
        follower_config = {"name": "Follower_Reverse", "strategy": "reverse", "copy_sl_tp": True}
        mock_config_manager.get_follower_config.return_value = follower_config
        
        event = create_mock_modify_event(position_id=master_pos_id, sl=1.1950, tp=1.2100)
        
        # 2. 执行
        trade_engine._handle_position_modify(event)

        # 3. 断言：对于反向策略，止损和止盈的值应该互换
        mock_account_manager.modify_position.assert_called_once_with("Follower_Reverse", follower_pos_id, 1.2100, 1.1950)

class TestLotSizeCalculation:
    """测试不同手数计算模式的逻辑。"""

    def test_build_request_with_lot_multiplier(self, trade_engine, mock_config_manager):
        """测试：手数模式为"倍率"时，跟单手数应是 主账户手数 * 倍率。"""
        # 1. 准备
        follower_config = {
            "name": "Follower_Multiplier", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 2.5
        }
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
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
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        master_event = create_mock_deal_event(volume=1.5)

        # 2. 执行
        trade_requests = trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言：手数应为固定的 0.77，忽略主账户的 1.5
        assert "Follower_Fixed" in trade_requests
        assert trade_requests["Follower_Fixed"]["volume"] == 0.77

class TestIntegrationFlow:
    """测试从事件处理到动作执行的完整流程。"""

    def test_process_deal_add_event_and_map_update(self, trade_engine, mock_config_manager, mock_account_manager):
        """测试：处理一个开仓事件后，应正确调用交易执行函数，并更新内部的持仓映射表。"""
        # 1. 准备：一个跟单账户、一个开仓事件，以及一个模拟的成功交易结果
        follower_config = {
            "name": "Follower1", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True, "magic": 11111
        }
        mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        
        event = create_mock_deal_event(position_id=200)
        
        # 模拟 AccountManager 返回一个成功的交易结果
        mock_result = MagicMock()
        mock_result.order = 500  # 跟单账户的持仓ID
        mock_account_manager.execute_trades_parallel.return_value = { "Follower1": {"status": "success", "result": mock_result} }

        # 2. 执行
        trade_engine.process_event(event)

        # 3. 断言
        # 断言交易执行函数被调用
        mock_account_manager.execute_trades_parallel.assert_called_once()
        
        # 断言持仓映射表被正确更新
        assert 200 in trade_engine.position_map
        assert "Follower1" in trade_engine.position_map[200]
        assert trade_engine.position_map[200]["Follower1"]["position_id"] == 500

if __name__ == '__main__':
    pytest.main() 