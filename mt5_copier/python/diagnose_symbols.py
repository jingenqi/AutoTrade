#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
MT5 Trade Copier - 符号映射诊断工具
用于诊断和修复符号映射问题
"""

import os
import sys
import logging
import json
import time
from typing import Dict, List, Optional, Any, Set
import MetaTrader5 as mt5

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - TradeCopier.SymbolDiagnose - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/symbol_diagnose.log", encoding="utf-8")
    ]
)

logger = logging.getLogger("TradeCopier.SymbolDiagnose")

def load_config(config_path: str = "config/config.json") -> Dict[str, Any]:
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"配置已从 {config_path} 成功加载。")
        return config
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        sys.exit(1)

def initialize_mt5(terminal_path: str, login: int, password: str, server: str) -> bool:
    """初始化MT5连接"""
    logger.info(f"正在初始化MT5: {terminal_path}")
    if not mt5.initialize(path=terminal_path):
        error = mt5.last_error()
        logger.error(f"MT5初始化失败: {error}")
        return False
    
    logger.info(f"正在登录账户: {login}@{server}")
    if not mt5.login(login=login, password=password, server=server):
        error = mt5.last_error()
        logger.error(f"MT5登录失败: {error}")
        mt5.shutdown()
        return False
    
    return True

def get_account_symbols(terminal_path: str, login: int, password: str, server: str) -> Set[str]:
    """获取账户可用的所有交易品种"""
    if not initialize_mt5(terminal_path, login, password, server):
        return set()
    
    try:
        symbols = mt5.symbols_get()
        symbol_names = {s.name for s in symbols}
        logger.info(f"账户 {login}@{server} 有 {len(symbol_names)} 个可用品种")
        return symbol_names
    except Exception as e:
        logger.error(f"获取品种列表失败: {e}")
        return set()
    finally:
        mt5.shutdown()

def find_similar_symbols(target: str, available_symbols: Set[str]) -> List[str]:
    """查找相似的品种名称"""
    similar = []
    target_lower = target.lower()
    
    # 完全匹配
    if target in available_symbols:
        return [target]
    
    # 不区分大小写匹配
    for symbol in available_symbols:
        if symbol.lower() == target_lower:
            similar.append(symbol)
    
    # 部分匹配
    if not similar:
        for symbol in available_symbols:
            if target_lower in symbol.lower() or symbol.lower() in target_lower:
                similar.append(symbol)
    
    return similar

def diagnose_symbol_mappings():
    """诊断符号映射问题"""
    config = load_config()
    
    # 获取主账户配置
    master_config = config.get("master_account", {})
    master_name = master_config.get("name", "未知")
    master_terminal = master_config.get("terminal_path", "")
    master_login = master_config.get("login", 0)
    master_password = master_config.get("password", "")
    master_server = master_config.get("server", "")
    
    logger.info(f"正在诊断主账户 {master_name} ({master_login}@{master_server}) 的符号...")
    master_symbols = get_account_symbols(master_terminal, master_login, master_password, master_server)
    
    if not master_symbols:
        logger.error("无法获取主账户的交易品种，请检查主账户配置")
        return
    
    # 常见外汇品种列表
    common_forex = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "USDCHF"]
    logger.info("检查主账户常见外汇品种可用性:")
    for symbol in common_forex:
        if symbol in master_symbols:
            logger.info(f"  ✓ {symbol} - 可用")
        else:
            similar = find_similar_symbols(symbol, master_symbols)
            if similar:
                logger.warning(f"  ✗ {symbol} - 不可用，但找到类似品种: {', '.join(similar)}")
            else:
                logger.error(f"  ✗ {symbol} - 不可用，且无类似品种")
    
    # 检查跟单账户
    follower_accounts = config.get("follower_accounts", [])
    for follower in follower_accounts:
        if not follower.get("enabled", False):
            continue
        
        follower_name = follower.get("name", "未知")
        follower_terminal = follower.get("terminal_path", "")
        follower_login = follower.get("login", 0)
        follower_password = follower.get("password", "")
        follower_server = follower.get("server", "")
        
        logger.info(f"\n正在诊断跟单账户 {follower_name} ({follower_login}@{follower_server}) 的符号...")
        follower_symbols = get_account_symbols(follower_terminal, follower_login, follower_password, follower_server)
        
        if not follower_symbols:
            logger.error(f"无法获取跟单账户 {follower_name} 的交易品种，请检查账户配置")
            continue
        
        # 获取符号映射
        symbol_mapping = follower.get("symbol_mapping", {})
        logger.info(f"账户 {follower_name} 的符号映射: {json.dumps(symbol_mapping, indent=2)}")
        
        # 检查映射的有效性
        logger.info("检查符号映射有效性:")
        for master_symbol, follower_symbol in symbol_mapping.items():
            if master_symbol not in master_symbols:
                logger.error(f"  ✗ 主账户符号 {master_symbol} 不存在")
                similar = find_similar_symbols(master_symbol, master_symbols)
                if similar:
                    logger.info(f"    建议: 主账户中可能应该使用 {similar[0]}")
            
            if follower_symbol not in follower_symbols:
                logger.error(f"  ✗ 跟单账户符号 {follower_symbol} 不存在")
                similar = find_similar_symbols(follower_symbol, follower_symbols)
                if similar:
                    logger.info(f"    建议: 跟单账户中可能应该使用 {similar[0]}")
            
            if master_symbol in master_symbols and follower_symbol in follower_symbols:
                logger.info(f"  ✓ 映射 {master_symbol} -> {follower_symbol} 有效")
        
        # 检查常见外汇品种
        logger.info("检查跟单账户常见外汇品种可用性:")
        for symbol in common_forex:
            mapped_symbol = symbol_mapping.get(symbol, symbol)
            if mapped_symbol in follower_symbols:
                logger.info(f"  ✓ {symbol} -> {mapped_symbol} - 可用")
            else:
                similar = find_similar_symbols(mapped_symbol, follower_symbols)
                if similar:
                    logger.warning(f"  ✗ {symbol} -> {mapped_symbol} - 不可用，但找到类似品种: {', '.join(similar)}")
                    # 建议添加映射
                    logger.info(f"    建议添加映射: \"{symbol}\": \"{similar[0]}\"")
                else:
                    logger.error(f"  ✗ {symbol} -> {mapped_symbol} - 不可用，且无类似品种")
        
        # 生成推荐的符号映射
        logger.info("生成推荐的符号映射:")
        recommended_mapping = {}
        for symbol in master_symbols:
            if symbol in follower_symbols:
                # 如果完全匹配，不需要映射
                continue
            
            similar = find_similar_symbols(symbol, follower_symbols)
            if similar:
                recommended_mapping[symbol] = similar[0]
        
        if recommended_mapping:
            logger.info(f"为账户 {follower_name} 推荐的符号映射:\n{json.dumps(recommended_mapping, indent=2)}")
        else:
            logger.info(f"账户 {follower_name} 不需要额外的符号映射")

def main():
    """主函数"""
    logger.info("开始诊断符号映射问题...")
    
    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)
    
    try:
        diagnose_symbol_mappings()
        logger.info("符号映射诊断完成")
    except Exception as e:
        logger.error(f"诊断过程中发生错误: {e}", exc_info=True)
    finally:
        # 确保MT5已关闭
        if mt5.terminal_info() is not None:
            mt5.shutdown()

if __name__ == "__main__":
    main() 