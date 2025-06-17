import time
import sys
import logging
import os
from datetime import datetime

# --- 将当前工作目录设置为脚本所在位置 ---
# 这确保了日志、配置文件等的相对路径能够可靠工作。
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
# ------------------------------------------

from core.config_manager import ConfigManager
from core.account_manager import AccountManager
from core.trade_engine import TradeEngine
from core.zmq_listener import ZmqListener
from config import settings

def setup_logging():
    # 设置整个应用程序的日志配置。
    # 如果日志目录不存在则创建
    os.makedirs('logs', exist_ok=True)
    
    # 配置日志
    log_filename = f"logs/trade_copier_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    logging.basicConfig(
        # level=logging.INFO,
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),
            logging.StreamHandler(sys.stdout)  # 也输出到控制台
        ]
    )
    
    # 将特定日志器的级别设置为适当的级别
    logging.getLogger("TradeCopier").setLevel(logging.INFO)
    logging.getLogger("MetaTrader5").setLevel(logging.WARNING)  # 减少 MT5 噪音
    
    logger = logging.getLogger("TradeCopier.Main")
    logger.info(f"日志已初始化。日志文件: {log_filename}")
    return logger

def main():
    # 主应用程序入口点。初始化并连接交易复制器的所有核心组件。
    # 首先设置日志
    logger = setup_logging()
    settings.print_zmq_config() # 打印当前 ZMQ 配置
    logger.info("--- 正在启动 MT5 交易复制控制器 ---")
    
    # 1. 初始化配置管理器
    print("[DEBUG] 正在初始化配置管理器...")
    config_manager = ConfigManager(config_path='config/config.json')
    if not config_manager.get_follower_accounts():
        logger.error("在 config.json 中未找到跟单账户或配置文件无效。正在退出。")
        sys.exit(1)
    print("[DEBUG] 配置管理器初始化成功。")

    # 2. 初始化账户管理器
    print("[DEBUG] 正在初始化账户管理器...")
    account_manager = AccountManager(config_manager)
    print("[DEBUG] 账户管理器初始化成功。")

    # 3. 初始化交易引擎
    print("[DEBUG] 正在初始化交易引擎...")
    trade_engine = TradeEngine(config_manager, account_manager)
    print("[DEBUG] 交易引擎初始化成功。")

    # 4. 初始化并启动 ZMQ 监听器
    print("[DEBUG] 正在初始化 ZMQ 监听器...")
    zmq_listener = ZmqListener(
        config_manager=config_manager,
        event_callback=trade_engine.process_event,
        state_sync_callback=trade_engine.sync_state
    )
    print("[DEBUG] ZMQ 监听器初始化成功。")
    
    print("[DEBUG] 正在启动 ZMQ 监听器线程...")
    zmq_listener.start()
    print("[DEBUG] ZMQ 监听器线程已启动。")
    
    # zmq_listener.is_running 是一个 Event 对象，需要用 is_set() 检查
    # if not zmq_listener.is_running.is_set():
    # 简化的检查，如果连接成功，ZmqListener 会保持运行
    # 如果监听器未运行，可能是因为连接失败，所以我们在这里检查它。
    time.sleep(2) # 给线程一些时间来尝试连接
    if not zmq_listener.running:
        logger.error("控制器启动失败。请检查 ZMQ 连接和 EA 状态。")
        # 清理可能已部分分配的资源
        account_manager.shutdown()
        zmq_listener.stop()
        sys.exit(1)

    logger.info("控制器正在运行。按 Ctrl+C 停止。")
    
    try:
        # 保持主线程活动以等待关闭信号
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("收到关闭信号 (Ctrl+C)。")
    finally:
        # 5. 优雅关闭序列
        logger.info("正在启动优雅关闭...")
        
        # 首先停止 ZMQ 监听器以防止处理新事件
        zmq_listener.stop()
        
        # 关闭账户管理器的线程池以完成任何活动交易
        account_manager.shutdown()
        
        logger.info("控制器已成功关闭。")

if __name__ == '__main__':
    main() 