import json
import os
import threading
import logging
from typing import Dict, Any, List, Optional

from .error_handler import handle_exceptions, ErrorCategory

logger = logging.getLogger("TradeCopier.ConfigManager")

class ConfigManager:
    # 初始化配置管理器
    def __init__(self, config_path: str = "config/config.json"):
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.lock = threading.RLock()
        self._load_config()

    # 从文件加载配置，如果文件不存在则抛出致命错误
    @handle_exceptions(category=ErrorCategory.CONFIG, re_raise=True)
    def _load_config(self):
        with self.lock:
            if not os.path.exists(self.config_path):
                # 如果配置文件不存在，这是一个致命错误，必须由用户解决
                error_msg = f"配置文件未找到: {os.path.abspath(self.config_path)}。请根据模板创建该文件。"
                logger.critical(error_msg)
                raise FileNotFoundError(error_msg)
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            logger.info(f"配置已从 {self.config_path} 成功加载。")

    # 将当前配置保存回文件
    @handle_exceptions(category=ErrorCategory.PERMANENT)
    def _save_config(self):
        with self.lock:
            # 在保存前，确保所有跟单账户的 is_master 标志为 False
            if "follower_accounts" in self.config and self.config["follower_accounts"]:
                for acc in self.config["follower_accounts"]:
                    if "is_master" in acc:
                        del acc["is_master"]
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            logger.info(f"配置已成功保存到 {self.config_path}。")

    # 获取单个配置项
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.lock:
            parts = key.split('.')
            current = self.config
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return default
            return current

    # 获取ZMQ设置
    def get_zmq_settings(self) -> Dict[str, Any]:
        return self.get_setting("zmq_settings", {})

    # 获取所有跟单账户的配置列表
    def get_follower_accounts(self) -> List[Dict[str, Any]]:
        return self.get_setting("follower_accounts", [])

    # 获取所有已启用的跟单账户配置
    def get_enabled_follower_configs(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            accounts = self.get_follower_accounts()
            return {
                acc["name"]: acc
                for acc in accounts
                if acc.get("enabled", False) and "name" in acc
            }

    # 按名称获取单个跟单账户的配置
    def get_follower_config(self, follower_name: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            for account in self.get_follower_accounts():
                if account.get("name") == follower_name:
                    return account
            return None

    # 重新加载配置
    def reload_config(self):
        logger.info("正在重新加载配置...")
        self._load_config()
        logger.info("配置重新加载完成。")

    # 添加一个新的跟单账户配置
    @handle_exceptions(category=ErrorCategory.CONFIG)
    def add_follower_account(self, account_config: dict):
        # 验证必需字段
        required_fields = ['name', 'login', 'password', 'server']
        for field in required_fields:
            if field not in account_config or not account_config[field]:
                raise ValueError(f"账户配置缺少必需字段: {field}")
                
        # 设置默认值
        defaults = {
            'enabled': True,
            'strategy': 'regular',
            'lot_mode': 'fixed',
            'lot_value': 0.01,
            'copy_sl_tp': True,
            'copy_pending': True,
            'max_slippage_pips': 3,
            'max_latency_ms': 500,
            'symbol_mapping': {}
        }
        
        for key, value in defaults.items():
            if key not in account_config:
                account_config[key] = value
        
        with self.lock:
            accounts = self.get_follower_accounts()
            if any(acc.get("name") == account_config.get("name") for acc in accounts):
                raise ValueError(f"账户名称 '{account_config['name']}' 已存在")
            accounts.append(account_config)
            self.config["follower_accounts"] = accounts
            self._save_config()
            logger.info(f"已添加跟单账户: {account_config.get('name')}")

    # 更新一个已有的跟单账户配置
    @handle_exceptions(category=ErrorCategory.CONFIG)
    def update_follower_account(self, account_name: str, new_config: dict):
        with self.lock:
            accounts = self.get_follower_accounts()
            account_found = False
            for i, account in enumerate(accounts):
                if account.get("name") == account_name:
                    accounts[i] = new_config
                    account_found = True
                    break
            if not account_found:
                raise ValueError(f"未找到账户: {account_name}")
            self.config["follower_accounts"] = accounts
            self._save_config()
            logger.info(f"已更新跟单账户: {account_name}")

    # 移除一个跟单账户配置
    @handle_exceptions(category=ErrorCategory.CONFIG)
    def remove_follower_account(self, account_name: str):
        with self.lock:
            accounts = self.get_follower_accounts()
            original_count = len(accounts)
            accounts = [acc for acc in accounts if acc.get("name") != account_name]
            if len(accounts) == original_count:
                raise ValueError(f"未找到账户: {account_name}")
            self.config["follower_accounts"] = accounts
            self._save_config()
            logger.info(f"已删除跟单账户: {account_name}")

    # 获取主账户的配置
    def get_master_config(self) -> Optional[Dict[str, Any]]:
        return self.get_setting("master_account")

    # 获取包含所有账户（主账户和跟单账户）的列表，并为每个账户添加角色信息
    def get_all_accounts(self) -> List[Dict[str, Any]]:
        with self.lock:
            all_accounts = []
            master = self.get_master_config()
            if master:
                master_copy = master.copy()
                master_copy['role'] = '主账户'
                all_accounts.append(master_copy)
            
            followers = self.get_follower_accounts()
            for acc in followers:
                follower_copy = acc.copy()
                follower_copy['role'] = '跟单账户'
                all_accounts.append(follower_copy)
            return all_accounts

    # 将指定的跟单账户设为新的主账户
    @handle_exceptions(category=ErrorCategory.CONFIG)
    def set_master_account(self, new_master_name: str):
        with self.lock:
            current_master = self.get_master_config()
            followers = self.get_follower_accounts()
            
            new_master_config = None
            new_master_index = -1

            # 在跟单账户列表中找到新的主账户
            for i, acc in enumerate(followers):
                if acc.get("name") == new_master_name:
                    new_master_config = acc
                    new_master_index = i
                    break
            
            if not new_master_config:
                raise ValueError(f"在跟单账户中未找到名为 '{new_master_name}' 的账户")

            # 从跟单账户列表中移除新的主账户
            followers.pop(new_master_index)
            # 将旧的主账户添加到跟单账户列表
            if current_master:
                followers.append(current_master)
            
            # 更新配置
            self.config['master_account'] = new_master_config
            self.config['follower_accounts'] = followers
            
            self._save_config()
            logger.info(f"已将账户 '{new_master_name}' 设置为新的主账户。")

    # 更新一个账户的配置（无论是主账户还是跟单账户）
    @handle_exceptions(category=ErrorCategory.CONFIG)
    def update_account(self, account_name: str, new_config: dict):
        with self.lock:
            # 检查是否在更新主账户
            master_config = self.get_master_config()
            if master_config and master_config.get("name") == account_name:
                self.config['master_account'] = new_config
                self._save_config()
                logger.info(f"已更新主账户 '{account_name}' 的配置。")
                return

            # 检查是否在更新跟单账户
            followers = self.get_follower_accounts()
            for i, acc in enumerate(followers):
                if acc.get("name") == account_name:
                    followers[i] = new_config
                    self.config['follower_accounts'] = followers
                    self._save_config()
                    logger.info(f"已更新跟单账户 '{account_name}' 的配置。")
                    return
            
            raise ValueError(f"未找到名为 '{account_name}' 的账户进行更新")

    # 获取主账户配置
    def get_master_account(self) -> Dict[str, Any]:
        """获取主账户配置"""
        with self.lock:
            return self.config.get("master_account", {})