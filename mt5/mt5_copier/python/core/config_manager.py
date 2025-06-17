import json
import os
import threading
import logging
from typing import Dict, Any, List

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
            "master_account": {
                "symbol_mapping": {
                    "EURUSD": "EURUSD"
                }
            },
            "follower_accounts": [
                {
                    "name": "Follower1_Regular",
                    "enabled": True,
                    "mt5_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
                    "login": 12345678,
                    "password": "your_password",
                    "server": "your_broker_server",
                    "risk_mode": "percentage", # "fixed" 或 "percentage"
                    "risk_percentage": 1.0,    # 如果是 percentage 模式，每笔交易风险 1%
                    "fixed_lot_size": 0.01,    # 如果是 fixed 模式，固定手数 0.01
                    "max_slippage_pips": 3     # 最大滑点（点）
                }
            ],
            "zmq_settings": {
                "transport": "tcp", # "ipc" 或 "tcp"
                "tcp_host": "localhost",
                "sync_port": 5555,
                "bus_port": 5556
            }
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            logger.info(f"已在 {self.config_path} 创建默认配置文件。")
        except IOError as e:
            logger.error(f"创建默认配置文件时发生 I/O 错误: {e}")
            raise

    def get_setting(self, key: str, default: Any = None) -> Any:
        # 获取给定键的配置设置。支持使用点号表示嵌套键（例如 "zmq_settings.transport"）。
        # Args:
        #     key: 要获取的设置的键（例如 "master_account.symbol_mapping"）。
        #     default: 如果找不到键，返回的默认值。
        # Returns:
        #     找到的设置值或默认值。
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

    def get_master_symbol_mapping(self) -> Dict[str, str]:
        # 获取主账户的交易品种映射。
        # Returns:
        #     交易品种映射字典。
        return self.get_setting("master_account.symbol_mapping", {})

    def get_follower_accounts(self) -> List[Dict[str, Any]]:
        # 获取所有跟单账户的配置列表。
        # Returns:
        #     跟单账户配置列表。
        return self.get_setting("follower_accounts", [])

    def get_follower_config(self, account_name: str) -> Dict[str, Any]:
        # 获取特定跟单账户的配置。
        # Args:
        #     account_name: 跟单账户的名称。
        # Returns:
        #     特定跟单账户的配置字典，如果未找到则为空字典。
        for account in self.get_follower_accounts():
            if account.get("name") == account_name:
                return account
        logger.warning(f"跟单账户 '{account_name}' 的配置未找到。")
        return {}

    def get_zmq_settings(self) -> Dict[str, Any]:
        # 获取 ZMQ 相关的设置。
        # Returns:
        #     ZMQ 设置字典。
        return self.get_setting("zmq_settings", {})

    def reload_config(self):
        # 重新加载配置。
        logger.info("正在重新加载配置...")
        self._load_config()
        logger.info("配置重新加载完成。")

    def update_config_value(self, key: str, value: Any):
        # 更新配置中的单个值并保存到文件。
        # Args:
        #     key: 要更新的设置的键（例如 "zmq_settings.transport"）。
        #     value: 要设置的新值。
        with self.lock:
            parts = key.split('.')
            current = self.config
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    if isinstance(current, dict):
                        current[part] = value
                        logger.info(f"配置键 '{key}' 已更新为 {value}。")
                    else:
                        logger.error(f"无法更新键 '{key}'：父元素不是字典。")
                        return
                else:
                    if isinstance(current, dict) and part in current:
                        current = current[part]
                    elif isinstance(current, dict):
                        current[part] = {}
                        current = current[part]
                    else:
                        logger.error(f"无法更新键 '{key}'：路径中存在非字典元素。")
                        return
            
            self._save_config()

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
            except Exception as e:
                logger.error(f"保存配置文件时发生意外错误: {e}")
                raise 