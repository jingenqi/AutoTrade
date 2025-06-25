"""
MT5 交易复制器 - 核心工作线程
处理GUI的后台处理任务
"""
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QThread
import logging
import threading
import time
from typing import Dict, List, Any, Optional, Callable

from core.config_manager import ConfigManager
from core.account_manager import AccountManager
from core.trade_engine import TradeEngine
from core.zmq_listener import ZmqListener
from core.error_handler import TradingErrorHandler
from core.events import BaseEvent
from .signals import GuiConnectionSignal

logger = logging.getLogger(f"TradeCopier.{__name__}")

# 创建一个自定义的日志处理器，用于将日志消息转发到GUI
class GUILogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setLevel(logging.INFO)
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            self.handleError(record)

class CoreWorker(QObject):
    """在独立线程中运行交易组件的后台工作者。"""

    # 信号定义
    log_received = pyqtSignal(str)
    account_status_updated = pyqtSignal(dict)  
    positions_updated = pyqtSignal(list)  
    error_occurred = pyqtSignal(str, str) 

    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.config_manager = None
        self.account_manager = None
        self.trade_engine = None
        self.error_handler = None
        self.zmq_listener = None
        self._running = False
        self._gui_log_handler = None

        self.connection_signal = GuiConnectionSignal()
        # 将内部信号连接到外部信号
        self.connection_signal.update_log.connect(self.log_received.emit)

    def setup(self, log_callback: Optional[Callable[[str], None]] = None):
        """设置核心组件"""
        try:
            # 初始化配置管理器
            self.config_manager = ConfigManager(self.config_path)
            
            # 添加GUI日志处理器
            if log_callback:
                self._gui_log_handler = GUILogHandler(log_callback)
                formatter = logging.Formatter('%(message)s')
                self._gui_log_handler.setFormatter(formatter)
                
                # 添加到根日志记录器
                root_logger = logging.getLogger("TradeCopier")
                root_logger.addHandler(self._gui_log_handler)
                
                # 添加到ZMQ日志记录器，确保交易事件能显示在GUI中
                zmq_logger = logging.getLogger("TradeCopier.ZmqListener")
                zmq_logger.addHandler(self._gui_log_handler)
                
                # 添加到交易引擎日志记录器
                trade_logger = logging.getLogger("TradeCopier.core.trade_engine")
                trade_logger.addHandler(self._gui_log_handler)
            
            # 初始化错误处理器
            self.error_handler = TradingErrorHandler(self.config_manager)
            
            # 初始化账户管理器
            self.account_manager = AccountManager(self.config_manager)
            
            # 初始化交易引擎
            self.trade_engine = TradeEngine(self.config_manager, self.account_manager, self.error_handler)
            
            # 注册持仓更新回调
            self.trade_engine.register_position_update_callback(self._on_positions_updated)
            
        except Exception as e:
            logger.error(f"Worker setup failed: {e}", exc_info=True)
            raise
            
    def start_trading(self):
        """启动跟单服务"""
        if self.is_running():
            self.log_received.emit("跟单服务已在运行")
            return
        
        try:
            # 重新加载配置，确保使用最新设置
            self.config_manager.reload_config()
            
            self.account_manager = AccountManager(self.config_manager)
            self.trade_engine = TradeEngine(self.config_manager, self.account_manager, self.error_handler)
            
            # 将 AccountManager 的信号连接到 Worker 的信号
            self.account_manager.connection_signal.update_account_status.connect(
                self.connection_signal.update_account_status
            )

            # 启动账户管理器
            self.account_manager.start(trade_callback=self.trade_engine.handle_trade_result)
            
            # 启动交易引擎
            self.trade_engine.start()
            
            # 初始化并启动ZMQ监听器
            self.zmq_listener = ZmqListener(
                self.config_manager,
                self.trade_engine.process_event,
                self.trade_engine.sync_state
            )
            self.zmq_listener.start()

            self._running = True
            
            logger.info("交易服务启动成功")
            
        except Exception as e:
            logger.error(f"交易服务启动失败: {e}", exc_info=True)
            self.stop_trading()
            raise

    def stop_trading(self):
        """停止交易服务"""
        if not self._running:
            return
            
        try:
            self._running = False
            
            # 停止ZMQ监听器
            if self.zmq_listener:
                self.zmq_listener.stop()
                self.zmq_listener = None
            
            # 停止交易引擎
            if self.trade_engine:
                self.trade_engine.stop()
            
            # 停止账户管理器
            if self.account_manager:
                self.account_manager.stop()
            
            logger.info("Trading service stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping trading service: {e}", exc_info=True)
            raise
            
    def is_running(self):
        """返回交易服务是否正在运行"""
        return self._running
        
    def reload_config(self):
        """重新加载配置"""
        try:
            self.config_manager.reload_config()
            return True
        except Exception as e:
            logger.error(f"Failed to reload config: {e}", exc_info=True)
            return False
            
    def refresh_status(self):
        """刷新所有账户状态"""
        if not self.is_running():
            self.log_received.emit("跟单服务未运行")
            return
            
        try:
            self.log_received.emit("正在刷新账户状态...")
            
            # The AccountManager now pushes updates, but a manual refresh can still be useful.
            # This is simplified because AccountManager is the source of truth.
            all_info = self.account_manager.get_all_account_info()
            
            # Prepare and emit status for all accounts based on the latest info
            account_statuses = []
            
            # Master Account
            master_config = self.config_manager.get_master_account()
            if master_config:
                master_info = self.trade_engine.get_master_account_info() if self.trade_engine else {}
                master_status = {
                    "name": master_config.get("name", "主账户"),
                    "status": "connected" if self.zmq_listener and self.zmq_listener.running else "disconnected",
                    **master_info
                }
                self.connection_signal.update_account_status.emit(master_status)

            # Follower Accounts
            for name, worker_info in all_info.items():
                status_data = {
                    'name': name,
                    **worker_info
                }
                self.connection_signal.update_account_status.emit(status_data)

            self.log_received.emit("手动账户状态刷新完成")
            
        except Exception as e:
            logger.error(f"Error preparing account status: {e}", exc_info=True)
    
    def _on_positions_updated(self, positions_list: List[Dict[str, Any]]) -> None:
        """处理来自交易引擎的持仓更新"""
        self.positions_updated.emit(positions_list)
    
    def cleanup(self):
        """清理资源"""
        # 移除GUI日志处理器
        if self._gui_log_handler:
            root_logger = logging.getLogger("TradeCopier")
            root_logger.removeHandler(self._gui_log_handler)
            
            zmq_logger = logging.getLogger("TradeCopier.ZmqListener")
            zmq_logger.removeHandler(self._gui_log_handler)
            
            trade_logger = logging.getLogger("TradeCopier.core.trade_engine")
            trade_logger.removeHandler(self._gui_log_handler)
            
            self._gui_log_handler = None