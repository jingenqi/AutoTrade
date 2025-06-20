"""
MT5 交易复制器 - 核心工作线程
处理GUI的后台处理任务
"""
from PyQt5.QtCore import QObject, pyqtSignal, QThread, pyqtSlot
import logging
import threading
import time
from typing import Dict, List, Any, Callable, Optional

from core.config_manager import ConfigManager
from core.account_manager import AccountManager
from core.trade_engine import TradeEngine
from core.zmq_listener import ZmqListener
from core.error_handler import CircuitBreaker, TradingErrorHandler
from core.connection_manager import ConnectionManager
from core.events import create_event_from_dict
# from .connection_manager import ConnectionManager # 根据您的项目结构，这个可能也需要调整

# 临时修复
HAS_CONNECTION_MANAGER = True

class CoreWorker(QObject):
    """在独立线程中运行交易组件的后台工作者。"""

    # 信号定义
    log_received = pyqtSignal(str)
    status_updated = pyqtSignal(str, str)  # 账户名, 状态信息
    account_status_updated = pyqtSignal(list)  # List[Dict] 账户状态
    positions_updated = pyqtSignal(list)  # List[Dict] 持仓数据
    trade_executed = pyqtSignal(dict)  # 交易执行结果
    connection_status_changed = pyqtSignal(str, str)  # 账户名, 状态
    error_occurred = pyqtSignal(str, str)  # 错误类型, 错误信息

    def __init__(self, config_path: str = "config/config.json") -> None:
        super().__init__()
        self.config_manager = ConfigManager(config_path)
        self.account_manager = AccountManager(self.config_manager)
        self.trade_engine = TradeEngine(self.config_manager, self.account_manager)
        
        # 连接管理器是可选的，取决于实现
        if HAS_CONNECTION_MANAGER:
            self.connection_manager = ConnectionManager(self.config_manager, self.account_manager)
        else:
            self.connection_manager = None
            
        self.zmq_listener = ZmqListener(
            config_manager=self.config_manager,
            event_callback=self.handle_trade_event,
            state_sync_callback=self.trade_engine.sync_state if hasattr(self.trade_engine, 'sync_state') else None
        )
        self.running = False
        self.status_timer = None
        self.logger = logging.getLogger("TradeCopier.Worker")
        
        # 注册回调函数
        self._register_callbacks()

    def _register_callbacks(self):
        """注册核心组件的回调函数"""
        # 注册交易引擎回调
        if hasattr(self.trade_engine, 'register_position_update_callback'):
            self.trade_engine.register_position_update_callback(self._on_positions_updated)
            
        # 注册账户管理器回调
        if hasattr(self.account_manager, 'register_trade_callback'):
            self.account_manager.register_trade_callback(self._on_trade_executed)
            
        # 如果可用，注册连接管理器回调
        if self.connection_manager and hasattr(self.connection_manager, 'register_status_callback'):
            self.connection_manager.register_status_callback(self._on_connection_status_changed)

    # ------------------------------------------------------------------
    # GUI控制的公共槽
    # ------------------------------------------------------------------
    def start_trading(self):
        """启动跟单服务"""
        if self.running:
            return
        self.running = True
        try:
            # 如果账户管理器已经关闭，先重新初始化它
            if hasattr(self.account_manager, 'restart'):
                self.account_manager.restart()
            
            # 执行一次性完整状态检查
            self.log_received.emit("正在获取初始账户状态...")
            self._update_all_statuses()
            
            # 启动ZMQ监听器
            self.zmq_listener.start()
            
            self.log_received.emit("跟单服务已启动。")
        except Exception as e:
            self.running = False
            self.log_received.emit(f"启动失败: {str(e)}")
            self.error_occurred.emit("启动错误", str(e))

    def stop_trading(self):
        """停止跟单服务"""
        if not self.running:
            return
        try:
            # 停止状态更新
            self._stop_status_updates()
            
            # 停止ZMQ监听器
            self.zmq_listener.stop()
            
            # 停止账户管理器
            self.account_manager.shutdown()
            
            # ConnectionManager 不再需要停止
                
            self.log_received.emit("跟单服务已停止")
        except Exception as e:
            self.log_received.emit(f"停止失败: {str(e)}")
            self.error_occurred.emit("停止错误", str(e))
        finally:
            # 无论如何都要设置running为False
            self.running = False

    def start(self):
        """保持向后兼容"""
        self.start_trading()

    def stop(self):
        """保持向后兼容"""
        self.stop_trading()

    # ------------------------------------------------------------------
    # 内部回调函数
    # ------------------------------------------------------------------
    def handle_trade_event(self, event_data: Dict[str, Any]) -> None:
        """处理来自ZMQ监听器的交易事件"""
        try:
            # 记录事件
            event_type = event_data.get("event_type", "UNKNOWN")
            symbol = event_data.get("symbol", "")
            volume = event_data.get("volume", 0)
            self.log_received.emit(f"收到交易事件: {event_type} {symbol} {volume}手")
            
            # 通过交易引擎处理事件
            self.trade_engine.process_event(event_data)
        except Exception as e:
            self.logger.error(f"Error handling trade event: {str(e)}")
            self.log_received.emit(f"处理交易事件错误: {str(e)}")
            self.error_occurred.emit("交易事件错误", str(e))
    
    def _on_positions_updated(self, positions: List[Dict[str, Any]]) -> None:
        """处理来自交易引擎的持仓更新"""
        self.positions_updated.emit(positions)
    
    def _on_trade_executed(self, account_name: str, result: Dict[str, Any]) -> None:
        """处理交易执行结果"""
        status = result.get("status", "unknown")
        message = result.get("message", "")
        
        if status == "success":
            # 修复：正确处理OrderSendResult对象
            result_obj = result.get('result')
            order_id = 0
            if result_obj:
                # 如果是OrderSendResult对象，直接访问其属性
                if hasattr(result_obj, 'order'):
                    order_id = result_obj.order
                # 如果是字典，使用get方法
                elif isinstance(result_obj, dict):
                    order_id = result_obj.get('order', 0)
                    
            self.status_updated.emit(account_name, f"交易成功: {order_id}")
        else:
            self.status_updated.emit(account_name, f"交易失败: {message}")
            
        self.trade_executed.emit({
            "account": account_name,
            "result": result
        })

        # 交易后，对该账户进行一次性的状态更新，以刷新余额等信息
        try:
            info = self.account_manager.get_account_info(account_name)
            if info:
                 status_update = {
                    "name": account_name,
                    "balance": getattr(info, "balance", 0.0),
                    "equity": getattr(info, "equity", 0.0),
                    "margin": getattr(info, "margin", 0.0),
                    "connection_status": "已连接"
                }
                 self.account_status_updated.emit([status_update])
        except Exception as e:
            self.logger.warning(f"交易后更新账户 {account_name} 状态失败: {e}")
    
    def _on_connection_status_changed(self, account_name: str, status: str) -> None:
        """处理连接状态变化"""
        self.connection_status_changed.emit(account_name, status)
        
    def _update_all_statuses(self):
        """获取所有已启用账户的完整状态并发出信号。"""
        try:
            statuses = []
            for acc_config in self.config_manager.get_follower_accounts():
                if not acc_config.get("enabled", False):
                    continue
                
                acc_name = acc_config.get("name", "")
                account_info = self.account_manager.get_account_info(acc_name)
                
                status_dict = {
                    "name": acc_name, "enabled": True, "balance": 0.0, "equity": 0.0, "margin": 0.0, "connection_status": "连接失败"
                }

                if account_info:
                    status_dict.update({
                        "balance": getattr(account_info, "balance", 0.0),
                        "equity": getattr(account_info, "equity", 0.0),
                        "margin": getattr(account_info, "margin", 0.0),
                        "connection_status": "已连接"
                    })
                statuses.append(status_dict)
            
            if statuses:
                self.account_status_updated.emit(statuses)
        except Exception as e:
            error_msg = f"更新账户状态时出错: {e}"
            self.logger.error(error_msg, exc_info=True)
            self.error_occurred.emit("状态更新错误", error_msg)

    @pyqtSlot()
    def request_status_update(self):
        """[GUI Slot] 手动触发所有账户的状态更新。"""
        if not self.running:
            self.log_received.emit("请先启动跟单服务再刷新状态。")
            return
        
        self.log_received.emit("正在手动刷新所有账户状态...")
        self._update_all_statuses()
        self.log_received.emit("账户状态刷新完成。")
        
    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    def _start_status_updates(self):
        """启动定期状态更新线程"""
        if self.status_timer is None:
            self.status_timer = threading.Thread(
                target=self._status_update_loop,
                daemon=True
            )
            self.status_timer.start()
    
    def _stop_status_updates(self):
        """停止状态更新线程"""
        self.status_timer = None
    
    def _status_update_loop(self):
        """定期状态更新的后台线程"""
        while self.running and self.status_timer is not None:
            try:
                # 获取所有账户的状态
                statuses = []
                for acc_config in self.config_manager.get_follower_accounts():
                    if not acc_config.get("enabled", False):
                        continue
                        
                    acc_name = acc_config.get("name", "")
                    status = {
                        "name": acc_name,
                        "enabled": True,
                        "balance": 0.0,
                        "equity": 0.0,
                        "margin": 0.0,
                        "connection_status": "未连接" if not self.running else "已连接"
                    }
                    
                    # 尝试获取账户信息
                    try:
                        # 首先尝试从账户管理器获取信息
                        if hasattr(self.account_manager, 'get_account_info'):
                            account_info = self.account_manager.get_account_info(acc_name)
                            if account_info:
                                status.update({
                                    "balance": getattr(account_info, "balance", 0.0),
                                    "equity": getattr(account_info, "equity", 0.0),
                                    "margin": getattr(account_info, "margin", 0.0),
                                    "connection_status": "已连接"
                                })
                        # 如果连接管理器可用，也尝试从那里获取信息
                        elif self.connection_manager and hasattr(self.connection_manager, 'get_account_info'):
                            account_info = self.connection_manager.get_account_info(acc_name)
                            if account_info:
                                status.update({
                                    "balance": account_info.get("balance", 0.0),
                                    "equity": account_info.get("equity", 0.0),
                                    "margin": account_info.get("margin", 0.0),
                                    "connection_status": account_info.get("status", "已连接")
                                })
                    except Exception as e:
                        self.logger.warning(f"获取账户 {acc_name} 信息时出错: {e}")
                        status["connection_status"] = f"连接错误: {str(e)}"
                            
                    statuses.append(status)
                
                # 如果有账户，发出状态更新
                if statuses:
                    self.account_status_updated.emit(statuses)
                    
            except Exception as e:
                self.logger.error(f"更新账户状态时出错: {str(e)}")
                
            # 休眠2秒
            time.sleep(2)

