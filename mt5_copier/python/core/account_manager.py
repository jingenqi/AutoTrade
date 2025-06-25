import MetaTrader5 as mt5
import logging
import time
import multiprocessing
from typing import Dict, Any, Optional, List, Callable
import uuid
import concurrent.futures
import threading
import queue

from .config_manager import ConfigManager
from .worker_process import WorkerProcess
from gui.signals import GuiConnectionSignal

logger = logging.getLogger(f"TradeCopier.{__name__}")

class AccountManager:
    """
    通过多进程模型管理多个跟单MT5账户的连接和交易执行。
    主进程不直接与MT5交互，而是通过IPC将任务分发给专用的工作进程。
    """
    def __init__(self, config_manager: ConfigManager):
        """
        初始化账户管理器。
        """
        self.config_manager = config_manager
        self.follower_configs = self.config_manager.get_enabled_follower_configs()
        self.lock = threading.RLock()
        self.worker_processes: Dict[str, multiprocessing.Process] = {}
        self.task_queues: Dict[str, multiprocessing.Queue] = {}
        self.result_queue = multiprocessing.Queue()
        self.stop_event = threading.Event()
        self.result_listener_thread = None
        self.is_running = False

        self._pending_results: Dict[str, Any] = {}
        self._pending_result_events: Dict[str, threading.Event] = {}
        self._trade_callback: Optional[Callable[[Dict], None]] = None

        # 用于GUI更新的信号
        self.connection_signal = GuiConnectionSignal()
        
        # PnL 更新
        self.pnl_update_thread = None
        self.pnl_update_interval = 5 # seconds

    def start(self, trade_callback: Callable[[Dict], None]):
        """启动账户管理器，创建并启动所有工作进程。"""
        if self.is_running:
            logger.warning("AccountManager 已经启动。")
            return

        logger.info("正在启动 AccountManager 及所有工作进程...")
        self._trade_callback = trade_callback
        self.is_running = True
        self.stop_event.clear()

        if not self.follower_configs:
            logger.warning("没有已启用的跟单账户，AccountManager 未启动任何工作进程。")
            return

        # 启动结果监听线程
        self.result_listener_thread = threading.Thread(target=self._listen_for_results, daemon=True)
        self.result_listener_thread.start()
        logger.info("结果监听线程已启动。")
        
        successful_workers = []
        failed_workers = []

        for name, config in self.follower_configs.items():
            try:
                task_queue = multiprocessing.Queue()
                
                worker = WorkerProcess(
                    account_config=config,
                    task_queue=task_queue,
                    result_queue=self.result_queue,
                )
                
                worker.start()
                
                logger.info(f"等待工作进程 '{name}' 初始化...")
                try:
                    # 等待来自工作进程的'initialized'信号
                    init_signal = self.result_queue.get(timeout=15)
                    if init_signal.get('status') == 'initialized' and init_signal.get('worker_name') == name:
                        self.worker_processes[name] = worker
                        self.task_queues[name] = task_queue
                        
                        account_info = init_signal.get('account_info', {})
                        # 立刻更新UI
                        self.connection_signal.update_account_status.emit({
                            'name': name, 'status': 'connected', **account_info
                        })
                        
                        successful_workers.append(name)
                        logger.info(f"✓ 工作进程 '{name}' 启动成功")
                    else:
                       logger.error(f"✗ 工作进程 '{name}' 初始化信号不正确: {init_signal}")
                       worker.terminate()
                       failed_workers.append((name, "初始化信号错误"))
                except queue.Empty:
                    logger.error(f"✗ 工作进程 '{name}' 在15秒内无响应，启动失败。")
                    worker.terminate()
                    failed_workers.append((name, "初始化超时"))
                    
            except Exception as e:
                logger.error(f"创建工作进程 '{name}' 时发生错误: {e}", exc_info=True)
                failed_workers.append((name, str(e)))

        # 只有在有工作进程成功启动时才启动更新器
        if successful_workers:
            self.pnl_update_thread = threading.Thread(target=self._account_info_updater, daemon=True, name="AccountInfoUpdater")
            self.pnl_update_thread.start()
        
        logger.info(f"AccountManager 启动完成: {len(successful_workers)} 个成功, {len(failed_workers)} 个失败")
        if failed_workers:
            logger.error("以下账户未能成功启动工作进程:")
            for name, reason in failed_workers:
                logger.error(f"  - {name}: {reason}")
        
        return successful_workers, failed_workers

    def _listen_for_results(self):
        """
        在一个专用线程中监听来自工作进程的结果，并将它们分派出去。
        """
        logger.info("结果监听循环开始...")
        while not self.stop_event.is_set():
            try:
                result = self.result_queue.get(timeout=0.1)
                correlation_id = result.get("correlation_id")
                if correlation_id:
                    with self.lock:
                        # If there is a trade callback, and it's not a direct request-response, use it
                        if self._trade_callback and result.get("type") == "trade_result":
                             self._trade_callback(result)
                        # 处理来自worker的账户信息更新
                        elif result.get("type") == "account_info_update":
                            account_name = result.get("worker_name")
                            if account_name in self.worker_processes:
                                self.connection_signal.update_account_status.emit({
                                    'name': account_name, 'status': 'connected', **result.get('payload', {})
                                })
                        else:
                            self._pending_results[correlation_id] = result
                            event = self._pending_result_events.get(correlation_id)
                            if event:
                                event.set()
                else:
                    logger.warning(f"收到了没有 correlation_id 的结果: {result}")
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"结果监听线程出现意外错误: {e}", exc_info=True)
        logger.info("结果监听循环已停止。")

    def stop(self):
        """关闭所有工作进程和管理器。"""
        if not self.is_running:
            return
            
        logger.info("正在关闭 AccountManager 及所有工作进程...")
        self.stop_event.set()

        if self.pnl_update_thread and self.pnl_update_thread.is_alive():
            self.pnl_update_thread.join(timeout=2)

        # 发送关闭指令给所有工作进程
        for name, queue in self.task_queues.items():
            if self.worker_processes[name].is_alive():
                try:
                    queue.put({'command': 'shutdown'})
                except Exception as e:
                    logger.error(f"发送关闭指令到 '{name}' 失败: {e}")

        # 等待所有进程终止
        for name, process in self.worker_processes.items():
            try:
                process.join(timeout=5)
                if process.is_alive():
                    logger.warning(f"工作进程 '{name}' 未能在5秒内终止，将强制终止。")
                    process.terminate()
            except Exception as e:
                logger.error(f"等待或终止进程 '{name}' 时出错: {e}")
        
        # 等待结果监听线程结束
        if self.result_listener_thread and self.result_listener_thread.is_alive():
            self.result_listener_thread.join(timeout=2)

        self.is_running = False
        
        # 更新UI状态
        for name in self.worker_processes.keys():
            self.connection_signal.update_account_status.emit({
                'name': name, 'status': 'disconnected', 'balance': 0, 
                'equity': 0, 'margin': 0, 'path': ''
            })

        self.worker_processes.clear()
        self.task_queues.clear()
        self.result_queue = None

        logger.info("AccountManager 已成功关闭。")

    def _account_info_updater(self):
        """Periodically request account info from all workers."""
        while not self.stop_event.wait(self.pnl_update_interval):
            with self.lock:
                for name, process in self.worker_processes.items():
                    if process.is_alive():
                        try:
                            self.task_queues[name].put_nowait({'command': 'get_account_info'})
                        except queue.Full:
                            logger.warning(f"指令队列 to '{name}' is full. Skipping account info update.")
                        except Exception as e:
                            logger.error(f"发送 get_account_info 指令到 '{name}' 失败: {e}")

    def get_account_info(self, account_name: str) -> Optional[Dict]:
        """获取单个账户的信息。"""
        response = self._send_request_and_wait(account_name, "get_account_info")
        if response and response.get("status") == "success":
            return response.get("payload", {})
        return None

    def get_symbol_info(self, account_name: str, symbol: str) -> Optional[Dict]:
        """从指定的工作进程获取品种信息。"""
        payload = {"symbol": symbol}
        response = self._send_request_and_wait(account_name, "get_symbol_info", payload)
        if response and response.get("status") == "success":
            return response.get("info")
        return None

    def get_all_symbols(self, account_name: str) -> Optional[List[str]]:
        """获取指定账户的所有可用交易品种。"""
        response = self._send_request_and_wait(account_name, "get_all_symbols")
        if response and response.get("status") == "success":
            return response.get("symbols", [])
        return None

    def get_all_follower_info(self) -> Dict[str, Any]:
        """并行获取所有已启用跟单账户的信息。"""
        if not self.is_running:
            logger.error("AccountManager 未运行。")
            return {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.follower_configs)) as executor:
            future_to_account = {
                executor.submit(self.get_account_info, name): name
                for name in self.follower_configs
            }
            results = {}
            for future in concurrent.futures.as_completed(future_to_account):
                account_name = future_to_account[future]
                try:
                    info = future.result()
                    if info:
                        results[account_name] = info
                except Exception as exc:
                    logger.error(f"为账户 {account_name} 获取信息时生成了异常: {exc}", exc_info=True)
        return results
        
    def register_trade_callback(self, callback):
        self._trade_callback = callback

    def execute_trades_parallel(self, trade_requests: List[Dict]) -> Dict[str, Any]:
        """并行地在多个账户上执行交易。"""
        if not self.is_running:
            logger.error("AccountManager 未运行，无法执行交易。")
            return {}
        
        # 过滤掉没有工作进程的账户请求
        valid_requests = []
        for request in trade_requests:
            account_name = request.get("account_name")
            if account_name in self.task_queues:
                valid_requests.append(request)
            else:
                logger.warning(f"账户 '{account_name}' 没有工作进程，跳过交易请求")
            
        if not valid_requests:
            logger.warning("没有有效的交易请求，所有账户都没有工作进程")
            return {}
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.follower_configs)) as executor:
            future_to_account = {
                executor.submit(self.execute_trade, request): request["account_name"]
                for request in valid_requests
            }

            results = {}
            for future in concurrent.futures.as_completed(future_to_account):
                account_name = future_to_account[future]
                try:
                    trade_result = future.result()
                    if trade_result:
                        results[account_name] = trade_result
                except Exception as exc:
                    logger.error(f"为账户 {account_name} 执行交易时生成了异常: {exc}", exc_info=True)
            return results

    def execute_trade(self, request: Dict) -> Optional[Dict]:
        """在单个账户上执行交易。"""
        account_name = request.pop("account_name")
        return self._send_request_and_wait(
            account_name,
            "execute_trade",
            payload=request
        )

    def get_positions(self, account_name: str, ticket: Optional[int] = None) -> Optional[List[Dict]]:
        """从指定的工作进程同步获取持仓信息。"""
        payload = {"ticket": ticket}
        response = self._send_request_and_wait(account_name, "get_positions", payload)
        if response and response.get("status") == "success":
            return response.get("payload", {})
        return None

    def execute_single_trade(self, account_name: str, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单笔交易请求
        """
        # 添加账户名到请求中
        request_copy = request.copy()
        request_copy["account_name"] = account_name
        return self.execute_trade(request_copy)

    def _send_request_async(self, account_name, action, payload=None):
        """
        异步发送请求到指定账户的工作进程。
        """
        # 生成唯一的相关ID
        correlation_id = self._generate_correlation_id()
        
        # 创建请求
        request = {
            "action": action,
            "correlation_id": correlation_id
        }
        
        if payload is not None:
            request["payload"] = payload
        
        # 创建Future
        future = concurrent.futures.Future()
        
        # 存储等待响应的请求
        with self.lock:
            self.pending_requests[correlation_id] = future
        
        # 发送请求到工作进程
        self.task_queues[account_name].put(request)
        
        return future

    def _process_results(self):
        """
        处理从工作进程返回的结果。
        
        此方法在一个单独的线程中运行，不断从结果队列中获取结果，
        并将其与等待的请求匹配。
        """
        while True:
            try:
                # 从结果队列中获取结果
                result = self.result_queue.get()
                
                if result is None:
                    # 结果队列已关闭
                    break
                
                # 提取相关ID
                correlation_id = result.get("correlation_id")
                
                if correlation_id is not None:
                    # 查找对应的Future
                    with self.lock:
                        future = self.pending_requests.pop(correlation_id, None)
                    
                    if future is not None:
                        # 设置Future的结果
                        future.set_result(result)
                    else:
                        self.logger.warning(f"收到未知相关ID的结果: {correlation_id}")
                else:
                    # 没有相关ID的结果，可能是错误或状态更新
                    account_name = result.get("account_name", "未知账户")
                    status = result.get("status")
                    message = result.get("message", "无消息")
                    
                    if status == "error":
                        self.logger.error(f"账户 {account_name} 报告错误: {message}")
                    else:
                        self.logger.info(f"账户 {account_name} 状态更新: {message}")
            
            except Exception as e:
                self.logger.error(f"处理结果时出错: {e}", exc_info=True)
                time.sleep(1)  # 防止快速错误循环

    def _generate_correlation_id(self):
        """
        生成唯一的相关ID。
        
        Returns:
            str: 唯一的相关ID
        """
        with self.lock:
            correlation_id = f"req-{self.next_correlation_id}"
            self.next_correlation_id += 1
            return correlation_id 

    def _test_worker_connection(self, account_name: str, task_queue: multiprocessing.Queue) -> bool:
        """测试工作进程是否正常响应"""
        try:
            # 先检查结果队列中是否有初始化状态消息
            start_time = time.time()
            while time.time() - start_time < 2:  # 2秒超时
                try:
                    result = self.result_queue.get_nowait()
                    if (result.get("account_name") == account_name and 
                        result.get("type") == "init_status"):
                        return result.get("status") == "success"
                    # 如果不是我们要的消息，放回队列
                    self.result_queue.put(result)
                except queue.Empty:
                    time.sleep(0.1)
            return False
        except Exception as e:
            logger.error(f"测试工作进程 '{account_name}' 连接时出错: {e}")
            return False

    def get_worker_status(self) -> Dict[str, str]:
        """获取所有工作进程的状态"""
        status = {}
        for name, worker in self.worker_processes.items():
            if worker.is_alive():
                # 发送ping命令测试响应
                response = self._send_request_and_wait(name, "ping", timeout=2.0)
                if response and response.get("status") == "success":
                    status[name] = "运行中"
                else:
                    status[name] = "无响应"
            else:
                status[name] = "已停止"
        
        # 检查配置中但没有工作进程的账户
        for name in self.follower_configs:
            if name not in status:
                if name not in self.task_queues:
                    status[name] = "未启动"
                else:
                    status[name] = "初始化失败"
        
        return status 

    def get_all_account_info(self) -> Dict[str, Any]:
        """
        获取所有工作进程的最新状态信息。
        注意: 此方法不会主动请求新信息，而是返回当前已知的状态。
        """
        all_info = {}
        with self.lock:
            for name, process in self.worker_processes.items():
                status = "running" if process.is_alive() else "stopped"
                # TODO: We can store the last known info to provide more details
                all_info[name] = {
                    "status": status, 
                    "pid": process.pid
                }
        return all_info 