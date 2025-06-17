#!/usr/bin/env python3
# 测试脚本，用于验证 MT5 交易复制系统是否正常工作。

import sys
import time
import logging
import os # 导入 os 模块以设置工作目录
from datetime import datetime

# --- 将当前工作目录设置为脚本所在位置 ---
# 这确保了日志、配置文件等的相对路径能够可靠工作。
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
# ------------------------------------------

# 设置日志
def setup_test_logging():
    # 为测试脚本设置日志。
    log_filename = f"logs/test_system_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger("TestSystem")
    logger.info(f"测试日志已初始化。日志文件: {log_filename}")
    return logger

def test_config_manager():
    # 测试 ConfigManager 功能。
    logger = logging.getLogger("TestSystem")
    logger.info("=== 正在测试 ConfigManager ===")
    
    try:
        from core.config_manager import ConfigManager
        
        # 初始化 ConfigManager
        config_manager = ConfigManager(config_path='config/config.json')
        
        # 测试获取跟单账户
        followers = config_manager.get_follower_accounts()
        logger.info(f"找到 {len(followers)} 个跟单账户")
        
        # 测试获取已启用的跟单账户
        enabled = config_manager.get_enabled_follower_accounts()
        logger.info(f"找到 {len(enabled)} 个已启用的跟单账户")
        
        for acc in enabled:
            logger.info(f"  - {acc['name']}: {acc.get('strategy', 'regular')} 策略, "
                       f"手数模式={acc.get('lot_mode', 'multiplier')}, "
                       f"手数值={acc.get('lot_value', 1.0)}")
        
        logger.info("ConfigManager 测试通过 ✓")
        return True
        
    except Exception as e:
        logger.error(f"ConfigManager 测试失败: {e}", exc_info=True)
        return False

def test_event_validation():
    # 使用 Pydantic 模型测试事件验证。
    logger = logging.getLogger("TestSystem")
    logger.info("=== 正在测试事件验证 ===")
    
    try:
        from core.events import DealAddEvent, OrderEvent, PositionModifyEvent
        
        # 测试有效的 DEAL_ADD 事件
        deal_data = {
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
        
        deal_event = DealAddEvent(**deal_data)
        logger.info(f"已创建有效的 DEAL_ADD 事件: ticket={deal_event.ticket}")
        
        # 测试有效的 ORDER_ADD 事件
        order_data = {
            "event_type": "ORDER_ADD",
            "ticket": 223456,
            "magic": 234567,
            "symbol": "GBPUSD",
            "type": "BUY_LIMIT",
            "state": "PLACED",
            "volume_initial": 0.2,
            "volume_current": 0.2,
            "price_open": 1.25000,
            "sl": 1.24500,
            "tp": 1.26000,
            "comment": "Pending order test",
            "time_setup_msc": 1234567890123,
            "time_done_msc": 0
        }
        
        order_event = OrderEvent(**order_data)
        logger.info(f"已创建有效的 ORDER_ADD 事件: ticket={order_event.ticket}")
        
        logger.info("事件验证测试通过 ✓")
        return True
        
    except Exception as e:
        logger.error(f"事件验证测试失败: {e}", exc_info=True)
        return False

def test_trade_engine_logic():
    # 在不进行实际交易的情况下测试 TradeEngine 逻辑。
    logger = logging.getLogger("TestSystem")
    logger.info("=== 正在测试 TradeEngine 逻辑 ===")
    
    try:
        from core.config_manager import ConfigManager
        from core.trade_engine import TradeEngine
        from unittest.mock import Mock
        
        # 创建模拟对象
        config_manager = ConfigManager(config_path='config/config.json')
        mock_account_manager = Mock()
        mock_account_manager.execute_trades_parallel.return_value = {
            "Follower1_Regular": {"status": "success", "result": Mock(order=999888)}
        }
        
        # 初始化 TradeEngine
        trade_engine = TradeEngine(config_manager, mock_account_manager)
        
        # 测试处理市价订单 (DEAL_ADD)
        market_order_json = """{
            "event_type": "DEAL_ADD",
            "ticket": 340059027,
            "order_ticket": 5005017203,
            "position_id": 5005017203,
            "magic": 0,
            "symbol": "EURUSD",
            "type": "BUY",
            "entry": "IN",
            "volume": 0.01,
            "price": 1.15585,
            "sl": 0.0,
            "tp": 0.0,
            "commission": 0.0,
            "swap": 0.0,
            "profit": 0.0,
            "comment": "",
            "time_msc": 1750118266759
        }"""
        
        logger.info("正在处理测试市价订单...")
        trade_engine.process_event(market_order_json)
        
        # 验证交易是否已尝试
        assert mock_account_manager.execute_trades_parallel.called
        logger.info("TradeEngine 正确处理了市价订单")
        
        # 测试处理挂单
        pending_order_json = """{
            "event_type": "ORDER_ADD",
            "ticket": 5005017210,
            "magic": 0,
            "symbol": "EURUSD",
            "type": "BUY_LIMIT",
            "state": "PLACED",
            "volume_initial": 0.01,
            "volume_current": 0.01,
            "price_open": 1.15000,
            "sl": 0.0,
            "tp": 0.0,
            "comment": "",
            "time_setup_msc": 1750118300000,
            "time_done_msc": 0
        }"""
        
        logger.info("正在处理测试挂单...")
        trade_engine.process_event(pending_order_json)
        
        logger.info("TradeEngine 逻辑测试通过 ✓")
        return True
        
    except Exception as e:
        logger.error(f"TradeEngine 逻辑测试失败: {e}", exc_info=True)
        return False

def main():
    # 运行所有测试。
    logger = setup_test_logging()
    logger.info("正在启动 MT5 交易复制系统测试...")
    
    tests = [
        test_config_manager,
        test_event_validation,
        test_trade_engine_logic,
        # test_account_manager (需要实际的 MT5 连接)
    ]

    all_passed = True
    for test_func in tests:
        if not test_func():
            all_passed = False
            logger.error(f"测试 {test_func.__name__} 失败。")
            # break # 如果一个测试失败就停止所有测试

    if all_passed:
        logger.info("所有系统测试通过！🎉")
    else:
        logger.error("部分系统测试失败。请检查日志以获取详细信息。")

if __name__ == '__main__':
    main() 