import unittest
from unittest.mock import Mock
import MetaTrader5 as mt5

from core.trade_engine import TradeEngine
from core.events import DealAddEvent

class TestTradeEngine(unittest.TestCase):
    """
    单元测试 TradeEngine.
    专注在不依赖外部环境的情况下，测试内部生成交易请求的逻辑。
    """

    def setUp(self):
        """在每个测试开始前，准备一个模拟的运行环境。"""
        self.mock_config_manager = Mock()
        self.mock_account_manager = Mock()
        
        # 使用模拟的依赖项来实例化交易引擎
        self.trade_engine = TradeEngine(
            config_manager=self.mock_config_manager,
            account_manager=self.mock_account_manager
        )

    def test_build_request_for_regular_open_buy(self):
        # 1. 准备: 配置模拟的ConfigManager
        follower_config = {
            "name": "Follower1_Regular", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True,
            "magic_number": 11111
        }
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]

        # 准备: 创建一个主账户买入事件的样本
        master_event = DealAddEvent(
            event_type="DEAL_ADD", ticket=100, order_ticket=10, position_id=200,
            magic=12345, symbol="EURUSD", type="BUY", entry="IN", volume=0.1,
            price=1.12345, sl=1.12000, tp=1.12800, commission=-0.1, swap=0, profit=0,
            comment="Regular buy", time_msc=123456789
        )

        # 2. 执行: 调用被测试的方法
        trade_requests = self.trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言: 检查生成的请求是否正确
        self.assertIn("Follower1_Regular", trade_requests)
        request = trade_requests["Follower1_Regular"]
        
        self.assertEqual(request["action"], mt5.TRADE_ACTION_DEAL)
        self.assertEqual(request["symbol"], "EURUSD")
        self.assertEqual(request["volume"], 0.1) # 倍率是 1.0
        self.assertEqual(request["type"], mt5.ORDER_TYPE_BUY) # 正向，方向相同
        self.assertEqual(request["sl"], 1.12000)
        self.assertEqual(request["tp"], 1.12800)
        self.assertEqual(request["comment"], "MasterPos:200") # 备注被系统格式化，用于跟踪
        self.assertEqual(request["magic"], 11111)

    def test_build_request_for_close_position(self):
        # 1. 准备: 配置一个副账户，并设置trade_map来模拟已开仓的状态
        follower_config = {"name": "Follower1_Regular", "enabled": True}
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]
        
        master_position_id = 200
        follower_position_id = 500
        self.trade_engine.trade_map = {master_position_id: {"Follower1_Regular": follower_position_id}}

        # 准备: 创建一个主账户平仓事件的样本 (一个买单持仓由一个卖单成交来关闭)
        master_event = DealAddEvent(
            event_type="DEAL_ADD", ticket=101, order_ticket=11, position_id=master_position_id,
            magic=12345, symbol="EURUSD", type="SELL", entry="OUT", volume=0.1,
            price=1.12500, sl=0, tp=0, commission=-0.1, swap=0, profit=15.5,
            comment="Regular close", time_msc=123459999
        )

        # 2. 执行: 调用被测试的方法
        trade_requests = self.trade_engine._build_trade_requests(master_event, is_open=False)

        # 3. 断言: 检查生成的平仓请求
        self.assertIn("Follower1_Regular", trade_requests)
        request = trade_requests["Follower1_Regular"]

        self.assertEqual(request["action"], mt5.TRADE_ACTION_DEAL)
        self.assertEqual(request["position"], follower_position_id) # 必须目标到正确的副账户持仓
        self.assertEqual(request["symbol"], "EURUSD")
        self.assertEqual(request["volume"], 0.1) # 平仓手数和主账户的平仓成交手数一致
        self.assertEqual(request["comment"], f"MasterPos:{master_position_id}")

    def test_build_request_for_reverse_open_sell_with_sl_tp_swap(self):
        # 测试反向策略：主账户买入，副账户应该卖出，并且SL/TP应该互换
        # 1. 准备: 配置一个反向策略的副账户
        follower_config = {
            "name": "Follower2_Reverse", "enabled": True, "strategy": "reverse",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True
        }
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]

        # 准备: 创建一个主账户买入事件
        master_event = DealAddEvent(
            event_type="DEAL_ADD", ticket=102, order_ticket=12, position_id=201,
            magic=67890, symbol="GBPUSD", type="BUY", entry="IN", volume=0.5,
            price=1.25000, sl=1.24000, tp=1.27000, commission=-0.5, swap=0,
            profit=0, comment="Reverse buy", time_msc=123460000
        )

        # 2. 执行
        trade_requests = self.trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言
        self.assertIn("Follower2_Reverse", trade_requests)
        request = trade_requests["Follower2_Reverse"]
        
        self.assertEqual(request["type"], mt5.ORDER_TYPE_SELL) # 方向相反
        self.assertEqual(request["sl"], 1.27000) # SL等于主账户的TP
        self.assertEqual(request["tp"], 1.24000) # TP等于主账户的SL

    def test_build_request_with_lot_multiplier(self):
        # 测试手数倍率：副账户手数 = 主账户手数 * 倍率
        # 1. 准备
        follower_config = {
            "name": "Follower3_Multiplier", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 2.5, "copy_sl_tp": False
        }
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]

        master_event = DealAddEvent(
            event_type="DEAL_ADD", ticket=103, order_ticket=13, position_id=202,
            magic=11223, symbol="USDJPY", type="SELL", entry="IN", volume=0.2,
            price=130.00, sl=0, tp=0, commission=-0.2, swap=0, profit=0,
            comment="Multiplier sell", time_msc=123470000
        )

        # 2. 执行
        trade_requests = self.trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言
        self.assertIn("Follower3_Multiplier", trade_requests)
        request = trade_requests["Follower3_Multiplier"]

        # 0.2 (主) * 2.5 (倍率) = 0.5 (副)
        self.assertAlmostEqual(request["volume"], 0.5)

    def test_build_request_with_fixed_lot(self):
        # 测试固定手数：副账户手数总是等于配置的固定值，忽略主账户手数
        # 1. 准备
        follower_config = {
            "name": "Follower4_Fixed", "enabled": True, "strategy": "regular",
            "lot_mode": "fixed", "lot_value": 0.77, "copy_sl_tp": False
        }
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]

        master_event = DealAddEvent(
            event_type="DEAL_ADD", ticket=104, order_ticket=14, position_id=203,
            magic=33445, symbol="AUDCAD", type="BUY", entry="IN", volume=1.5,
            price=0.9000, sl=0, tp=0, commission=-1.0, swap=0, profit=0,
            comment="Fixed lot buy", time_msc=123480000
        )
        
        # 2. 执行
        trade_requests = self.trade_engine._build_trade_requests(master_event, is_open=True)

        # 3. 断言
        self.assertIn("Follower4_Fixed", trade_requests)
        request = trade_requests["Follower4_Fixed"]
        
        self.assertEqual(request["volume"], 0.77) # 总是使用固定值


if __name__ == '__main__':
    unittest.main() 