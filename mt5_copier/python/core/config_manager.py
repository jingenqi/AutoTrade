import json
import os
import threading
import logging
from typing import Dict, Any, List, Optional

# 设置日志
logger = logging.getLogger("TradeCopier.ConfigManager")

class ConfigManager:
    # 管理应用程序的配置，包括加载、验证和提供对设置的访问。配置从 JSON 文件加载，并支持实时更新。
    def __init__(self, config_path: str = "config/config.json"):
        # 初始化配置管理器。
        # Args:
        #     config_path: 配置文件的路径。
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.lock = threading.RLock() # 使用可重入锁，因为可能会有嵌套的锁获取
        self._load_config()

    @property
    def EA_MAGIC(self) -> int:
        """
        获取EA标识号 (Magic Number)
        
        Returns:
            用于标识交易的数字（默认为12345）
        """
        with self.lock:
            return self.config.get("magic_number", 12345)

    def _load_config(self):
        # 从指定路径加载或重新加载配置文件。
        with self.lock:
            try:
                if not os.path.exists(self.config_path):
                    logger.warning(f"配置文件未找到: {self.config_path}。正在创建默认配置。")
                    self._create_default_config()
                    
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.info(f"配置已从 {self.config_path} 成功加载。")
                # 记录完整的配置内容（仅用于调试，生产环境可能不需要）
                logger.debug(f"加载的配置: {json.dumps(self.config, indent=2)}")

            except json.JSONDecodeError as e:
                logger.error(f"配置文件 {self.config_path} 解析错误: {e}")
                raise
            except IOError as e:
                logger.error(f"读取配置文件 {self.config_path} 时发生 I/O 错误: {e}")
                raise
            except Exception as e:
                logger.error(f"加载配置文件时发生意外错误: {e}")
                raise

    def _create_default_config(self):
        # 创建一个默认的 config.json 文件。
        default_config = {
            "magic_number": 12345,
            "master_account": {
                "login": 999999,
                "symbol_mapping": {
                    "EURUSD": "EURUSD"
                }
            },
            "follower_accounts": [
                {
                    "name": "Follower1_Regular",
                    "enabled": True,
                    "login": 12345678,
                    "password": "your_password",
                    "server": "your_broker_server",
                    "strategy": "regular", # "regular" or "reverse"
                    "lot_mode": "multiplier", # "multiplier", "fixed", "risk_percentage"
                    "lot_value": 1.0,
                    "copy_sl_tp": True,
                    "max_slippage_pips": 3
                }
            ],
            "zmq_settings": {
                "transport": "tcp", # "ipc" 或 "tcp"
                "req_port": 5555,
                "sub_port": 5556
            }
        }
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"已在 {self.config_path} 创建默认配置文件。")
        except IOError as e:
            logger.error(f"创建默认配置文件时发生 I/O 错误: {e}")
            raise

    def get_setting(self, key: str, default: Any = None) -> Any:
        # 获取给定键的配置设置。支持使用点号表示嵌套键（例如 "zmq_settings.transport"）。
        with self.lock:
            parts = key.split('.')
            current = self.config
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    logger.warning(f"配置键 '{key}' 的一部分 '{part}' 未找到。返回默认值。")
                    return default
            return current

    def get_master_account(self) -> Optional[Dict[str, Any]]:
        """获取主账户配置。"""
        with self.lock:
            return self.config.get("master_account")

    def get_follower_accounts(self) -> List[Dict[str, Any]]:
        # 获取所有跟单账户的配置列表。
        with self.lock:
            return self.get_setting("follower_accounts", [])

    def get_enabled_follower_configs(self) -> Dict[str, Dict[str, Any]]:
        """获取所有已启用的跟单账户配置，以账户名为键。"""
        with self.lock:
            accounts = self.get_follower_accounts()
            return {
                acc["name"]: acc
                for acc in accounts
                if acc.get("enabled", False) and "name" in acc
            }
            
    def get_enabled_follower_accounts(self) -> List[Dict[str, Any]]:
        """
        获取所有已启用的跟单账户配置列表。
        
        Returns:
            已启用的跟单账户配置列表
        """
        with self.lock:
            return [
                acc for acc in self.get_follower_accounts()
                if acc.get("enabled", False)
            ]
            
    def get_follower_account(self, name: str) -> Optional[Dict[str, Any]]:
        """按名称获取单个跟单账户的配置。"""
        with self.lock:
            for account in self.get_follower_accounts():
                if account.get("name") == name:
                    return account
            return None
            
    def get_zmq_settings(self) -> Dict[str, Any]:
        # 获取 ZMQ 相关的设置。
        return self.get_setting("zmq_settings", {})

    def get_follower_config(self, follower_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定跟单账户的完整配置
        
        Args:
            follower_name: 跟单账户的名称
            
        Returns:
            如果找到账户，则返回其完整配置；否则返回 None
        """
        with self.lock:
            for account in self.get_follower_accounts():
                if account.get("name") == follower_name:
                    return account
            logger.warning(f"未找到跟单账户 '{follower_name}' 的配置")
            return None

    def reload_config(self):
        # 重新加载配置。
        logger.info("正在重新加载配置...")
        self._load_config()
        logger.info("配置重新加载完成。")

    def _save_config(self):
        # 将当前配置保存回文件。
        with self.lock:
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=4, ensure_ascii=False)
                logger.info(f"配置已成功保存到 {self.config_path}。")
            except IOError as e:
                logger.error(f"保存配置文件 {self.config_path} 时发生 I/O 错误: {e}")
                raise

    def add_follower_account(self, account_config: dict):
        """添加跟单账户配置"""
        with self.lock:
            if "follower_accounts" not in self.config:
                self.config["follower_accounts"] = []
            
            existing_names = [acc.get("name") for acc in self.config["follower_accounts"]]
            if account_config.get("name") in existing_names:
                logger.error(f"账户名称 '{account_config.get('name')}' 已存在。")
                raise ValueError(f"账户名称 '{account_config['name']}' 已存在")
            
            self.config["follower_accounts"].append(account_config)
            self._save_config()
            logger.info(f"已添加跟单账户: {account_config.get('name')}")
            
    def update_follower_account(self, account_name: str, new_config: dict):
        """更新跟单账户配置"""
        with self.lock:
            accounts = self.get_follower_accounts()
            account_found = False
            for i, account in enumerate(accounts):
                if account.get("name") == account_name:
                    accounts[i] = new_config
                    account_found = True
                    break
            
            if not account_found:
                logger.error(f"尝试更新但未找到账户: {account_name}")
                raise ValueError(f"未找到账户: {account_name}")
            
            self.config["follower_accounts"] = accounts
            self._save_config()
            logger.info(f"已更新跟单账户: {account_name}")
            
    def remove_follower_account(self, account_name: str):
        """删除跟单账户配置"""
        with self.lock:
            accounts = self.get_follower_accounts()
            original_count = len(accounts)
            accounts = [acc for acc in accounts if acc.get("name") != account_name]
            
            if len(accounts) == original_count:
                logger.warning(f"尝试删除但未找到账户: {account_name}")
                raise ValueError(f"未找到账户: {account_name}")

            self.config["follower_accounts"] = accounts
            self._save_config()
            logger.info(f"已删除跟单账户: {account_name}")

            