import unittest
from unittest.mock import patch, MagicMock, Mock

from core.trade_engine import TradeEngine
from core.config_manager import ConfigManager
# from core.account_manager import AccountManager # 不再直接导入，避免加载mt5库

class TestIntegration(unittest.TestCase):

    def setUp(self):
        # 使用一个模拟的ConfigManager
        self.mock_config_manager = Mock()
        
        # 同样使用一个模拟的AccountManager，避免加载真实模块
        self.mock_account_manager = Mock()
        
        self.trade_engine = TradeEngine(
            config_manager=self.mock_config_manager,
            account_manager=self.mock_account_manager
        )

    def test_process_open_buy_event_and_map_update(self):
        # 1. 准备: 定义从主账户EA传来的JSON数据
        json_payload = """
        {
            "event_type": "DEAL_ADD", "ticket": 100, "order_ticket": 10,
            "position_id": 200, "magic": 12345, "symbol": "EURUSD",
            "type": "BUY", "entry": "IN", "volume": 0.1, "price": 1.12345,
            "sl": 1.12000, "tp": 1.12800, "commission": 0, "swap": 0,
            "profit": 0, "comment": "Test Buy", "time_msc": 123456789
        }
        """

        # 准备: 为模拟的ConfigManager提供返回值
        follower_config = {
            "name": "Follower1_Regular", "enabled": True, "strategy": "regular",
            "lot_mode": "multiplier", "lot_value": 1.0, "copy_sl_tp": True
        }
        self.mock_config_manager.get_enabled_follower_accounts.return_value = [follower_config]

        # 准备: 编排模拟的AccountManager的返回值
        # 模拟一个成功的交易结果
        mock_result = MagicMock()
        mock_result.order = 500  # 副账户成功开仓后的持仓ID
        
        self.mock_account_manager.execute_trades_parallel.return_value = {
            "Follower1_Regular": {
                "status": "success",
                "result": mock_result
            }
        }

        # 2. 执行: 调用交易引擎的核心处理方法
        self.trade_engine.process_event(json_payload)

        # 3. 断言
        # 断言AccountManager的执行方法被调用过一次
        self.mock_account_manager.execute_trades_parallel.assert_called_once()
        
        # 断言trade_map被正确更新
        self.assertIn(200, self.trade_engine.trade_map) # 键是主账户的持仓ID
        self.assertIn("Follower1_Regular", self.trade_engine.trade_map[200])
        self.assertEqual(self.trade_engine.trade_map[200]["Follower1_Regular"], 500) # 值是副账户的持仓ID


if __name__ == '__main__':
    unittest.main() 