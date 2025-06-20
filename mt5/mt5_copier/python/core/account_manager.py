import MetaTrader5 as mt5
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, Callable
from threading import RLock
import time

from .config_manager import ConfigManager

logger = logging.getLogger("TradeCopier.AccountManager")

class AccountManager:
    """
    管理多个跟单MT5账户的连接和交易执行。
    采用安全的"即用即连"模式，并在每次连接后验证身份，以防止终端劫持。
    """
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='MT5Executor')
        self.executor_lock = RLock()
        self.lock = RLock()
        self._trade_callback: Optional[Callable[[str, Dict], None]] = None
        self._is_shutdown = False

        master_account_config = self.config_manager.get_master_account()
        self.master_login = master_account_config.get("login") if master_account_config else None
        
        if self.master_login:
            logger.info(f"已设置主账户登录号: {self.master_login}，将用于防止终端劫持。")
        else:
            logger.warning("配置文件中未找到主账户信息，无法执行终端劫持检查。")

    def _ensure_executor_running(self):
        """确保线程池执行器正在运行，如果已关闭则重新创建"""
        with self.executor_lock:
            if self._is_shutdown or self.executor._shutdown:
                logger.info("线程池已关闭，正在重新初始化...")
                self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='MT5Executor')
                self._is_shutdown = False
                logger.info("线程池已重新初始化")

    def _get_connection(self, account_name: str) -> Optional[mt5]:
        """
        通过"探查-验证"模式安全地获取MT5连接，绝不传递登录凭证。
        此方法假设用户已经手动启动了所有需要的MT5终端，只负责连接已运行的终端。
        会严格验证连接账号，确保不会连接到主账户。
        """
        acc_config = self.config_manager.get_follower_account(account_name)
        if not acc_config or not acc_config.get("enabled", False):
            return None

        expected_login = acc_config.get("login")
        if not expected_login:
            logger.error(f"账户 '{account_name}' 在配置中缺少登录号。")
            return None

        # 获取主账户登录号，用于确保不会连接到主账户
        if self.master_login and expected_login == self.master_login:
            logger.error(f"试图将主账户 {self.master_login} 作为跟单账户 '{account_name}' 连接，这是不允许的。")
            return None

        # 检查新的和旧的路径配置键，并优先使用新的
        terminal_path = acc_config.get("terminal_path") or acc_config.get("mt5_path")
        if acc_config.get("mt5_path"):
            logger.warning(f"配置键 'mt5_path' 已弃用，请在配置文件中更新为 'terminal_path' 以保持兼容性。")

        # 优先策略：如果配置了终端路径，则使用该路径进行精确连接
        if terminal_path:
            logger.debug(f"尝试使用指定路径连接到账户 '{account_name}': {terminal_path}")
            # 增加重试机制，因为即使有路径，第一次连接也可能因为时机问题失败
            for i in range(3): # 尝试3次
                if mt5.initialize(path=terminal_path):
                    account_info = mt5.account_info()
                    if account_info and account_info.login == expected_login:
                        logger.info(f"成功通过路径连接到跟单账户 '{account_name}' ({expected_login})。")
                        return mt5
                    else:
                        actual_login = account_info.login if account_info else "N/A"
                        logger.warning(f"通过路径 '{terminal_path}' 连接到了错误的账户。预期: {expected_login}, 实际: {actual_login}。正在关闭连接...")
                        mt5.shutdown()
                else:
                    error = mt5.last_error()
                    logger.warning(f"使用路径 '{terminal_path}' 初始化MT5失败 (尝试 {i+1}/3)。错误: {error}")

                if i < 2:
                    time.sleep(0.5) # 重试前短暂等待
            
            logger.error(f"多次尝试后仍无法通过路径 '{terminal_path}' 连接到正确的账户 {expected_login}。")
            logger.error("请确认：1. 路径是否正确。2. 对应的MT5终端已启动并登录。3. 没有以管理员权限运行MT5而普通权限运行本程序。")
            return None

        # 备用策略：如果未配置路径，则使用旧的"探查-验证"模式
        logger.warning(f"账户 '{account_name}' 未配置 'terminal_path'。将尝试自动发现终端，此方式连接不稳定，强烈建议进行配置。")
        server = acc_config.get("server", "未知")
        max_attempts = 5
        for i in range(max_attempts):
            try:
                if mt5.initialize():
                    account_info = mt5.account_info()
                    
                    if account_info and self.master_login and account_info.login == self.master_login:
                        logger.warning(f"连接尝试 {i+1}/{max_attempts}: 错误连接到主账户 ({self.master_login})，而不是跟单账户 '{account_name}' ({expected_login})。正在断开重试...")
                        mt5.shutdown()
                        time.sleep(1.0)
                        continue
                    
                    if account_info and account_info.login == expected_login:
                        logger.info(f"成功发现并连接到跟单账户 '{account_name}' ({expected_login})。")
                        return mt5
    
                    actual_login = account_info.login if account_info else "N/A"
                    logger.debug(f"连接尝试 {i+1}/{max_attempts}: 连接到非预期的终端 ({actual_login}), 需要 ({expected_login})。正在断开重试...")
                    mt5.shutdown()
                else:
                    logger.warning(f"连接尝试 {i+1}/{max_attempts}: mt5.initialize() 失败。")
    
                wait_time = 0.5 + (i * 0.2)
                if i < max_attempts - 1:
                    time.sleep(wait_time)
            except Exception as e:
                logger.error(f"连接尝试 {i+1}/{max_attempts} 发生异常: {e}")
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                time.sleep(1.0)

        logger.error(f"未能找到已启动的 MT5 终端用于跟单账户 '{account_name}' (登录号: {expected_login}, 服务器: {server})。")
        logger.error(f"请确保该账户的 MT5 终端已手动启动并正确登录。")
        return None

    @staticmethod
    def _release_connection(mt5_instance: Optional[mt5]):
        """释放（关闭）一个MT5连接。"""
        if mt5_instance:
            mt5_instance.shutdown()

    def execute_trade(self, account_name: str, trade_request: Dict[str, Any]) -> Dict[str, Any]:
        """在单个账户上安全地执行交易请求。"""
        mt5_conn = self._get_connection(account_name)
        if not mt5_conn:
            return {"status": "error", "message": f"无法建立到 {account_name} 的安全连接。"}

        try:
            logger.info(f"在账户 {account_name} 上执行交易: {trade_request}")
            result = mt5_conn.order_send(trade_request)
            
            if result is None:
                error_message = f"订单发送失败，MT5返回None。错误: {mt5_conn.last_error()}"
                logger.error(error_message)
                return {"status": "error", "message": error_message}

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                error_message = f"交易失败: {result.comment} (Retcode: {result.retcode})"
                logger.warning(error_message)
                return {"status": "error", "message": error_message, "result": result}
            
            success_message = f"交易成功，订单号: {result.order}"
            logger.info(success_message)
            return {"status": "success", "message": success_message, "result": result}

        except Exception as e:
            logger.error(f"在账户 {account_name} 上交易时发生意外: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
        finally:
            self._release_connection(mt5_conn)

    def execute_trades_parallel(self, trade_requests: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """并行执行一批交易请求。"""
        # 使用新的通用并行执行器
        jobs = {
            name: (lambda n, r: lambda: self.execute_trade(n, r))(name, req)
            for name, req in trade_requests.items()
        }
        return self.run_in_parallel(jobs)
            
    def run_in_parallel(self, jobs: Dict[str, Callable[[], Any]]) -> Dict[str, Any]:
        """
        并行运行一个字典的作业，其中键是标识符，值是可调用函数。
        
        Args:
            jobs: 一个字典，{job_name: job_function}
            
        Returns:
            一个字典，包含每个作业的结果，{job_name: result}
        """
        if not jobs:
            return {}
        
        self._ensure_executor_running()
        
        from concurrent.futures import as_completed
        with self.executor_lock:
            future_to_name = {
                self.executor.submit(job): name
                for name, job in jobs.items()
            }

        results = {}
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                job_result = future.result()
                results[name] = job_result
                # 对于交易，我们仍然希望触发回调
                if name in jobs and "execute_trade" in jobs[name].__qualname__:
                    if self._trade_callback:
                        self._trade_callback(name, job_result)
            except Exception as exc:
                logger.error(f"并行任务 for '{name}' 异常: {exc}", exc_info=True)
                results[name] = {"status": "error", "message": str(exc)}
        return results

    def get_account_info(self, account_name: str) -> Optional[Any]:
        """安全地获取指定账户的信息。"""
        mt5_conn = self._get_connection(account_name)
        if not mt5_conn:
            return None
        
        try:
            return mt5_conn.account_info()
        finally:
            self._release_connection(mt5_conn)

    def shutdown(self):
        """关闭线程池。"""
        with self.executor_lock:
            logger.info("正在关闭 AccountManager 线程池...")
            self._is_shutdown = True
            self.executor.shutdown(wait=True)
            logger.info("AccountManager 已关闭。")

    def restart(self):
        """重新启动账户管理器"""
        with self.executor_lock:
            if self._is_shutdown or self.executor._shutdown:
                logger.info("正在重新启动 AccountManager...")
                self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix='MT5Executor')
                self._is_shutdown = False
                logger.info("AccountManager 已重新启动。")

    def register_trade_callback(self, callback: Callable[[str, Dict], None]):
        """注册交易执行后的回调。"""
        self._trade_callback = callback

    def normalize_volume(self, account_name: str, symbol: str, volume: float) -> float:
        """Normalize lot size according to symbol settings."""
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return volume

        volume = max(symbol_info.volume_min, min(volume, symbol_info.volume_max))
        step = symbol_info.volume_step
        if step > 0:
            volume = round(volume / step) * step
        return volume

    def execute_single_trade(self, account_name: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单笔交易请求
        
        Args:
            account_name: 账户名称
            request: 交易请求字典
            
        Returns:
            交易结果字典，包含status和其他信息
        """
        # 直接调用内部方法执行交易，这样可以利用现有的重试机制
        return self.execute_trade(account_name, request) 