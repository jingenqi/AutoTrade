"""
MT5 Trade Copier - System Health Check
检查系统各个组件是否正常工作
"""
import os
import sys
import json
import MetaTrader5 as mt5
from core.config_manager import ConfigManager
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HealthCheck")

def check_config():
    """检查配置文件"""
    print("\n检查配置文件...")
    try:
        config_manager = ConfigManager("config/config.json")
        print("✓ 配置文件加载成功")
        
        # 检查必要的配置项
        if config_manager.get_zmq_settings():
            print("✓ ZMQ设置已配置")
        else:
            print("✗ 缺少ZMQ设置")
            
        followers = config_manager.get_follower_accounts()
        if followers:
            print(f"✓ 找到 {len(followers)} 个跟单账户")
            for acc in followers:
                print(f"  - {acc.get('name', 'Unknown')}: {'已启用' if acc.get('enabled') else '已禁用'}")
        else:
            print("✗ 没有配置跟单账户")
            
        return True
    except Exception as e:
        print(f"✗ 配置文件错误: {e}")
        return False

def check_mt5():
    """检查MT5连接"""
    print("\n检查MT5连接...")
    try:
        if not mt5.initialize():
            print(f"✗ MT5初始化失败: {mt5.last_error()}")
            return False
            
        terminal_info = mt5.terminal_info()
        if terminal_info:
            print(f"✓ MT5终端已连接")
            print(f"  - 终端版本: {terminal_info.version}")
            print(f"  - 公司: {terminal_info.company}")
        
        mt5.shutdown()
        return True
    except Exception as e:
        print(f"✗ MT5检查失败: {e}")
        return False

def check_dependencies():
    """检查依赖包"""
    print("\n检查依赖包...")
    required_packages = [
        "MetaTrader5",
        "zmq",
        "PyQt5"
    ]
    
    all_ok = True
    for package in required_packages:
        try:
            __import__(package)
            print(f"✓ {package} 已安装")
        except ImportError:
            print(f"✗ {package} 未安装")
            all_ok = False
            
    return all_ok

def main():
    print("=== MT5自动跟单系统健康检查 ===")
    
    results = {
        "配置文件": check_config(),
        "依赖包": check_dependencies(),
        "MT5连接": check_mt5()
    }
    
    print("\n=== 检查结果汇总 ===")
    all_passed = True
    for component, status in results.items():
        status_str = "✓ 正常" if status else "✗ 异常"
        print(f"{component}: {status_str}")
        if not status:
            all_passed = False
            
    if all_passed:
        print("\n所有检查已通过！系统可以正常运行。")
        return 0
    else:
        print("\n部分检查未通过，请根据上述信息修复问题。")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 