#!/usr/bin/env python
"""
MT5 Trade Copier - 诊断工具

用于检查跟单系统的各个组件，帮助排查问题
"""
import os
import sys
import json
import logging
import time
from typing import Dict, Any, List, Optional

# 确保当前目录在路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 设置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("TradeCopier.Diagnose")

# 导入必要的模块
try:
    import MetaTrader5 as mt5
    from core.config_manager import ConfigManager
    from core.account_manager import AccountManager
    from core.worker_process import WorkerProcess
except ImportError as e:
    logger.error(f"导入模块失败: {e}")
    logger.error("请确保已安装所有依赖: pip install -r requirements.txt")
    sys.exit(1)

def check_mt5_installation() -> bool:
    """检查MT5是否正确安装"""
    logger.info("检查MT5安装...")
    try:
        if mt5.__version__:
            logger.info(f"MT5版本: {mt5.__version__}")
            return True
        else:
            logger.error("无法获取MT5版本信息")
            return False
    except Exception as e:
        logger.error(f"MT5安装检查失败: {e}")
        return False

def check_config_file(config_path: str = "config/config.json") -> Optional[Dict[str, Any]]:
    """检查配置文件是否有效"""
    logger.info(f"检查配置文件: {config_path}")
    try:
        config_manager = ConfigManager(config_path)
        config = config_manager.config
        
        # 检查主账户配置
        master_config = config.get("master_account", {})
        if not master_config:
            logger.error("配置文件中缺少主账户配置")
        else:
            logger.info(f"主账户配置: 名称={master_config.get('name')}, 服务器={master_config.get('server')}")
            
        # 检查跟单账户配置
        follower_accounts = config.get("follower_accounts", [])
        if not follower_accounts:
            logger.error("配置文件中没有跟单账户")
        else:
            logger.info(f"找到 {len(follower_accounts)} 个跟单账户配置")
            for i, account in enumerate(follower_accounts):
                logger.info(f"跟单账户 {i+1}: 名称={account.get('name')}, 服务器={account.get('server')}, 启用={account.get('enabled', False)}")
                
                # 检查符号映射
                symbol_mapping = account.get("symbol_mapping", {})
                if symbol_mapping:
                    logger.info(f"账户 {account.get('name')} 的符号映射: {symbol_mapping}")
                    
        # 检查ZMQ设置
        zmq_settings = config.get("zmq_settings", {})
        if not zmq_settings:
            logger.error("配置文件中缺少ZMQ设置")
        else:
            logger.info(f"ZMQ设置: 传输={zmq_settings.get('transport')}, 主机={zmq_settings.get('tcp_host')}, 端口={zmq_settings.get('req_port')}/{zmq_settings.get('sub_port')}")
            
        return config
    except Exception as e:
        logger.error(f"检查配置文件失败: {e}")
        return None

def test_mt5_connection(account_config: Dict[str, Any]) -> bool:
    """测试与MT5终端的连接"""
    account_name = account_config.get("name", "未知")
    terminal_path = account_config.get("terminal_path")
    login = account_config.get("login")
    password = account_config.get("password")
    server = account_config.get("server")
    
    logger.info(f"测试账户 {account_name} 的MT5连接...")
    
    if not terminal_path:
        logger.error(f"账户 {account_name} 未指定MT5终端路径")
        return False
        
    if not os.path.exists(terminal_path):
        logger.error(f"账户 {account_name} 的MT5终端路径不存在: {terminal_path}")
        return False
        
    try:
        # 初始化MT5
        logger.info(f"正在初始化MT5: {terminal_path}")
        if not mt5.initialize(path=terminal_path):
            error = mt5.last_error()
            logger.error(f"MT5初始化失败: {error}")
            return False
            
        # 登录
        logger.info(f"正在登录账户: {login}@{server}")
        if not mt5.login(login=login, password=password, server=server):
            error = mt5.last_error()
            logger.error(f"登录失败: {error}")
            mt5.shutdown()
            return False
            
        # 获取账户信息
        account_info = mt5.account_info()
        if not account_info:
            logger.error("无法获取账户信息")
            mt5.shutdown()
            return False
            
        logger.info(f"成功连接到账户: {account_info.login}@{account_info.server}")
        logger.info(f"账户余额: {account_info.balance}, 净值: {account_info.equity}")
        
        return True
    except Exception as e:
        logger.error(f"连接MT5时发生错误: {e}")
        return False
    finally:
        if mt5.terminal_info():
            mt5.shutdown()

def check_symbol_availability(account_config: Dict[str, Any], symbols: List[str]) -> Dict[str, bool]:
    """检查账户是否可以访问指定的交易品种"""
    account_name = account_config.get("name", "未知")
    terminal_path = account_config.get("terminal_path")
    login = account_config.get("login")
    password = account_config.get("password")
    server = account_config.get("server")
    
    logger.info(f"检查账户 {account_name} 的交易品种可用性...")
    
    results = {}
    
    try:
        # 初始化MT5
        if not mt5.initialize(path=terminal_path):
            error = mt5.last_error()
            logger.error(f"MT5初始化失败: {error}")
            return {s: False for s in symbols}
            
        # 登录
        if not mt5.login(login=login, password=password, server=server):
            error = mt5.last_error()
            logger.error(f"登录失败: {error}")
            mt5.shutdown()
            return {s: False for s in symbols}
            
        # 检查每个品种
        for symbol in symbols:
            info = mt5.symbol_info(symbol)
            if not info and mt5.symbol_select(symbol, True):
                time.sleep(0.2)
                info = mt5.symbol_info(symbol)
                
            if info:
                logger.info(f"账户 {account_name} 可以访问品种 {symbol}")
                results[symbol] = True
            else:
                logger.error(f"账户 {account_name} 无法访问品种 {symbol}")
                results[symbol] = False
                
        return results
    except Exception as e:
        logger.error(f"检查品种可用性时发生错误: {e}")
        return {s: False for s in symbols}
    finally:
        if mt5.terminal_info():
            mt5.shutdown()

def check_symbol_mapping(config: Dict[str, Any]) -> None:
    """检查主账户和跟单账户之间的符号映射"""
    logger.info("检查符号映射...")
    
    master_config = config.get("master_account", {})
    follower_accounts = config.get("follower_accounts", [])
    
    # 获取主账户可用的品种
    master_symbols = []
    if test_mt5_connection(master_config):
        try:
            if mt5.initialize(path=master_config.get("terminal_path")):
                if mt5.login(login=master_config.get("login"), password=master_config.get("password"), server=master_config.get("server")):
                    symbols = mt5.symbols_get()
                    if symbols:
                        master_symbols = [s.name for s in symbols]
                        logger.info(f"主账户有 {len(master_symbols)} 个可用品种")
                    else:
                        logger.error("无法获取主账户的可用品种")
                mt5.shutdown()
        except Exception as e:
            logger.error(f"获取主账户品种时发生错误: {e}")
    
    # 检查每个跟单账户的符号映射
    for account in follower_accounts:
        if not account.get("enabled", False):
            logger.info(f"跳过已禁用的账户: {account.get('name')}")
            continue
            
        symbol_mapping = account.get("symbol_mapping", {})
        
        if not symbol_mapping:
            logger.warning(f"账户 {account.get('name')} 没有配置符号映射，将使用相同的符号名")
            
        # 检查映射的品种是否在跟单账户中可用
        mapped_symbols = []
        for master_symbol, follower_symbol in symbol_mapping.items():
            mapped_symbols.append(follower_symbol)
            if master_symbol in master_symbols:
                logger.info(f"主账户品种 {master_symbol} 映射到跟单账户 {account.get('name')} 的 {follower_symbol}")
            else:
                logger.warning(f"主账户品种 {master_symbol} 在主账户中不可用，但已映射到跟单账户的 {follower_symbol}")
                
        # 检查跟单账户是否可以访问这些品种
        if mapped_symbols:
            availability = check_symbol_availability(account, mapped_symbols)
            for symbol, available in availability.items():
                if not available:
                    logger.error(f"跟单账户 {account.get('name')} 无法访问映射的品种 {symbol}")

def main():
    """主函数"""
    logger.info("开始诊断MT5跟单系统...")
    
    # 检查MT5安装
    if not check_mt5_installation():
        logger.error("MT5安装检查失败，请确保MT5 Python API正确安装")
        sys.exit(1)
        
    # 检查配置文件
    config = check_config_file()
    if not config:
        logger.error("配置文件检查失败，请确保config.json格式正确")
        sys.exit(1)
        
    # 测试主账户连接
    master_config = config.get("master_account", {})
    if not test_mt5_connection(master_config):
        logger.error("主账户连接测试失败")
    
    # 测试跟单账户连接
    follower_accounts = config.get("follower_accounts", [])
    for account in follower_accounts:
        if account.get("enabled", False):
            if not test_mt5_connection(account):
                logger.error(f"跟单账户 {account.get('name')} 连接测试失败")
                
    # 检查符号映射
    check_symbol_mapping(config)
    
    logger.info("诊断完成")

if __name__ == "__main__":
    main() 