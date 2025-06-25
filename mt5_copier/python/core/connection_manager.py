import logging
from typing import Callable, Optional

from .config_manager import ConfigManager
from .account_manager import AccountManager

logger = logging.getLogger("TradeCopier.ConnectionManager")

class ConnectionManager:
    # 负责按需检查账户状态，并向UI报告
    def __init__(self, config_manager: ConfigManager, account_manager: AccountManager):
        self.config_manager = config_manager
        self.account_manager = account_manager
        self._status_callback: Optional[Callable[[str, str], None]] = None

    # 一次性检查所有已启用账户的初始连接状态
    def check_initial_statuses(self):
        logger.info("正在执行一次性初始账户状态检查...")
        accounts = self.config_manager.get_follower_accounts()
        for acc_config in accounts:
            name = acc_config.get("name")
            if not name: continue

            if not acc_config.get("enabled", False):
                self._update_status(name, "已禁用")
                continue
            
            # 委托 AccountManager 获取信息，后者将任务分派给工作进程
            info = self.account_manager.get_account_info(name)
            
            if info and info.get('info'):
                status = "已连接"
                login = info['info'].get('login')
                server = info['info'].get('server')
                logger.info(f"账户 '{name}' ({login}@{server}) 的初始状态: {status}")
            else:
                status = "连接失败"
                logger.warning(f"账户 '{name}' 的初始状态: {status}")
            
            self._update_status(name, status)

    # 注册状态更新的回调函数
    def register_status_callback(self, callback: Callable[[str, str], None]):
        self._status_callback = callback

    # 调用回调函数更新状态
    def _update_status(self, name: str, status: str):
        if self._status_callback:
            self._status_callback(name, status)