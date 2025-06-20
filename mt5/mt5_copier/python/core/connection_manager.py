"""Connection manager for MT5 terminals.

This module manages connections to multiple MetaTrader5 terminals.
It can auto-discover running terminals, connect to them after the user
starts the terminal manually, and monitor the connection state.
"""

import logging
import threading
import time
from typing import Dict, Any, Callable, Optional, List

import MetaTrader5 as mt5

from .config_manager import ConfigManager
from .account_manager import AccountManager

logger = logging.getLogger("TradeCopier.ConnectionManager")

class ConnectionManager:
    """
    负责按需检查账户状态，并向UI报告。
    不再进行后台轮询，以避免终端劫持风险。
    """
    def __init__(self, config_manager: ConfigManager, account_manager: AccountManager):
        self.config_manager = config_manager
        self.account_manager = account_manager
        self._status_callback: Optional[Callable[[str, str], None]] = None

    def check_initial_statuses(self):
        """
        一次性检查所有已启用账户的初始连接状态。
        此方法应在用户启动服务时调用。
        """
        logger.info("正在执行一次性初始账户状态检查...")
        accounts = self.config_manager.get_follower_accounts()
        for acc_config in accounts:
            if not acc_config.get("enabled", False):
                continue
            
            name = acc_config.get("name")
            info = self.account_manager.get_account_info(name)
            
            status = "已连接" if info else "连接失败"
            logger.info(f"账户 '{name}' 的初始状态: {status}")
            
            if self._status_callback:
                self._status_callback(name, status)

    def register_status_callback(self, callback: Callable[[str, str], None]):
        """注册状态更新的回调函数。"""
        self._status_callback = callback
