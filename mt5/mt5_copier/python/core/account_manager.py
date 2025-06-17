import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any
import logging

import MetaTrader5 as mt5

from core.config_manager import ConfigManager

# 设置日志
logger = logging.getLogger("TradeCopier.AccountManager")

class AccountManager:
    # 管理多个跟单 MT5 账户的连接和交易执行。
    # 使用线程池并行执行交易，确保低延迟。
    def __init__(self, config_manager: ConfigManager):
        # 初始化 AccountManager。
        # Args:
        #     config_manager: ConfigManager 的实例。
        self.config_manager = config_manager
        # 工作线程数可以根据配置调整
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='MT5Executor')
        
        # 为每个账户创建锁，以防止初始化时的竞争条件
        follower_names = [acc['name'] for acc in self.config_manager.get_follower_accounts()]
        self.connection_locks: Dict[str, threading.Lock] = {name: threading.Lock() for name in follower_names}
        logger.info(f"AccountManager 已初始化，服务于: {', '.join(follower_names)}")

    def _execute_single_order(self, account_name: str, request: Dict[str, Any]) -> Dict[str, Any]:
        # 连接到单个 MT5 账户，执行交易，然后断开连接。
        # 此方法设计为线程安全，并在线程池中运行。
        # 
        # Args:
        #     account_name: 跟单账户的名称。
        #     request: 符合 mt5.order_send() 的交易请求字典。
        #     
        # Returns:
        #     包含交易执行结果的字典。
        config = self.config_manager.get_follower_config(account_name)
        if not config or not config.get('enabled', False):
            return {"status": "error", "message": f"账户 '{account_name}' 已禁用或未找到。"}

        # 获取此特定账户的锁
        with self.connection_locks[account_name]:
            logger.debug(f"为 {account_name} 执行交易: {request}")
            try:
                # 初始化与特定 MT5 终端的连接
                if not mt5.initialize(path=config['mt5_path'], 
                                      login=config['login'], 
                                      password=config['password'], 
                                      server=config['server']):
                    error = mt5.last_error()
                    logger.error(f"为 {account_name} 初始化 MT5 失败: {error}")
                    mt5.shutdown()
                    return {"status": "error", "message": f"初始化失败: {error}"}
                
                # 发送订单
                result = mt5.order_send(request)
                
                # 操作后立即断开连接
                mt5.shutdown()

                if result is None:
                    last_error = mt5.last_error()
                    logger.error(f"为 {account_name} 发送订单失败。MT5 返回 None。错误: {last_error}")
                    return {"status": "error", "message": f"订单发送失败，返回 None。MT5 错误: {last_error}"}

                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    logger.error(f"为 {account_name} 发送订单失败。代码: {result.retcode}, 注释: {result.comment}")
                    return {"status": "error", "retcode": result.retcode, "comment": result.comment, "result_obj": result}
                else:
                    logger.info(f"为 {account_name} 发送订单成功。订单号: {result.order}")
                    return {"status": "success", "result": result}

            except Exception as e:
                logger.error(f"在 {account_name} 上交易时发生意外异常: {e}", exc_info=True)
                # 确保在异常时也调用 shutdown
                mt5.shutdown()
                return {"status": "fatal_error", "message": str(e)}

    def execute_trades_parallel(self, trade_requests: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        # 使用线程池并行执行一批交易请求。
        # 等待所有交易完成并返回其结果。
        # 
        # Args:
        #     trade_requests: 映射账户名称到其交易请求字典的字典。
        #     
        # Returns:
        #     映射账户名称到其交易结果字典的字典。
        if not trade_requests:
            return {}

        logger.debug(f"正在将 {len(trade_requests)} 笔交易提交到执行池。")
        
        from concurrent.futures import as_completed
        future_to_account = {
            self.executor.submit(self._execute_single_order, name, req): name
            for name, req in trade_requests.items()
        }

        results = {}
        for future in as_completed(future_to_account):
            account_name = future_to_account[future]
            try:
                results[account_name] = future.result()
            except Exception as exc:
                logger.error(f"线程池中为 {account_name} 生成了异常: {exc}", exc_info=True)
                results[account_name] = {"status": "fatal_error", "message": str(exc)}
        
        logger.debug(f"执行池完成处理 {len(results)} 笔交易。")
        return results

    def shutdown(self):
        # 优雅地关闭线程池执行器。
        logger.info("正在关闭 AccountManager 的线程池...")
        self.executor.shutdown(wait=True)
        logger.info("线程池已关闭。") 