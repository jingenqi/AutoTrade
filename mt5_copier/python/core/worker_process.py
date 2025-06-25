import logging
import time
import MetaTrader5 as mt5
import multiprocessing
from typing import Dict, Any, Optional, List
from multiprocessing.synchronize import Lock

from .error_handler import handle_exceptions, with_retry, ErrorCategory, CircuitBreaker
from .constants import TradeAction

logger = logging.getLogger("TradeCopier.WorkerProcess")

# 定义一个特定的异常，用于初始化失败时触发重试
class MT5InitializationError(Exception):
    pass

class WorkerProcess(multiprocessing.Process):
    # 初始化工作进程
    def __init__(self, account_config: Dict[str, Any], task_queue: multiprocessing.Queue, result_queue: multiprocessing.Queue):
        super().__init__()
        self.account_config = account_config
        self.task_queue = task_queue
        self.result_queue = result_queue
        self.name = f"WorkerProcess-{self.account_config.get('name', 'Unknown')}"
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=account_config.get("circuit_breaker_threshold", 5),
            recovery_timeout=account_config.get("circuit_breaker_timeout", 60)
        )
        self._mt5_connected = False
        self._connection_lock = Lock()
        
        self.command_handlers = {
            "execute_trade": self._execute_trade_action,
            "get_account_info": self._get_account_info_action,
            "get_symbol_info": self._get_symbol_info_action,
            "get_positions": self._get_positions_action,
            "ping": self._ping_action,
            "get_all_symbols": self._get_all_symbols_action,
        }

    # 工作进程的主执行循环
    def run(self):
        """主工作循环，处理来自主进程的指令。"""
        self.name = self.account_config["name"]
        
        # 发送初始化信号
        if self._initialize_mt5():
            account_info = self._get_mt5_account_info()
            self.result_queue.put({
                'status': 'initialized', 
                'worker_name': self.name,
                'account_info': account_info
            })
        else:
            self.result_queue.put({'status': 'initialization_failed', 'worker_name': self.name})
            return # 初始化失败则直接退出

        while True:
            try:
                task = self.task_queue.get()
                command = task.get("command")

                if command == 'shutdown':
                    break # 退出循环
                
                payload = task.get("payload")
                correlation_id = task.get("correlation_id")

                handler = self.command_handlers.get(command)
                if handler:
                    result = handler(payload)
                    # 对于有相关ID的请求，返回结果
                    if correlation_id:
                        response = {"correlation_id": correlation_id, "payload": result}
                        if "status" not in result:
                           response["status"] = "success"
                        else:
                           response["status"] = result["status"]
                        self.result_queue.put(response)
                # 对于周期性更新任务，直接返回结果
                elif command == 'get_account_info':
                    info = self._get_mt5_account_info()
                    self.result_queue.put({
                        "type": "account_info_update",
                        "worker_name": self.name,
                        "payload": info
                    })
                else:
                    logger.warning(f"Worker '{self.name}' received unknown command: {command}")
            except Exception as e:
                logger.error(f"Worker '{self.name}' error in main loop: {e}", exc_info=True)
        
        self._shutdown_mt5()
        logger.info(f"Worker '{self.name}' has been shut down.")

    # 初始化与MT5终端的连接
    def _initialize_mt5(self):
        try:
            return self.circuit_breaker.call(self._do_initialize_mt5)
        except Exception as e:
            logger.critical(f"[{self.name}] MT5 初始化在多次尝试后失败: {e}")
            return False

    def _do_initialize_mt5(self):
        account_name = self.account_config.get("name")
        login = self.account_config.get("login")
        password = self.account_config.get("password")
        server = self.account_config.get("server")
        terminal_path = self.account_config.get("terminal_path")

        # 检查是否有指定终端路径
        if not terminal_path:
            logger.warning(f"[{account_name}] 未指定MT5终端路径，跳过初始化")
            raise MT5InitializationError(f"[{account_name}] 未指定MT5终端路径")
            
        logger.info(f"[{account_name}] 正在使用指定路径初始化MT5: {terminal_path}")
        
        if not mt5.initialize(path=terminal_path):
            error_code = mt5.last_error()[0] if isinstance(mt5.last_error(), tuple) else mt5.last_error()
            error_msg = f"[{account_name}] MT5初始化失败: {mt5.last_error()}, 错误代码: {error_code}"
            logger.error(error_msg)
            raise MT5InitializationError(error_msg)
            
        logger.debug(f"[{account_name}] MT5初始化成功，尝试登录账户")
        
        if not mt5.login(
            login=int(login),
            password=password,
            server=server,
        ):
            error_msg = f"Worker '{self.name}' MT5 login failed for account {login}. Error: {mt5.last_error()}"
            logger.error(error_msg)
            mt5.shutdown()
            raise MT5InitializationError(error_msg)
            
        logger.info(f"Worker '{self.name}' successfully connected to account {login}.")
        self._mt5_connected = True
        return True

    def _get_mt5_account_info(self):
        """获取并返回MT5账户信息。"""
        if not self._mt5_connected:
            return {}
        try:
            info = mt5.account_info()
            if info:
                return {
                    "balance": info.balance,
                    "equity": info.equity,
                    "margin": info.margin,
                    "path": mt5.terminal_info().path
                }
            return {}
        except Exception as e:
            logger.error(f"Worker '{self.name}' failed to get account info: {e}")
            return {}

    # 解析并分派任务
    @handle_exceptions(category=ErrorCategory.LOGIC)
    def _handle_task(self, task: Dict[str, Any]):
        account_name = self.account_config.get("name")
        command = task.get("command")
        payload = task.get("payload", {})
        correlation_id = task.get("correlation_id")
        
        # 检查MT5是否仍然连接
        if not mt5.terminal_info():
            logger.warning(f"[{account_name}] MT5连接已断开，尝试重新初始化")
            try:
                self._initialize_mt5()
            except Exception as e:
                logger.error(f"[{account_name}] 重新初始化MT5失败: {e}")
                self.result_queue.put({
                    "account_name": account_name, "status": "error",
                    "payload": {"status": "error", "message": f"MT5重连失败: {str(e)}"}, 
                    "correlation_id": correlation_id,
                    "type": "trade_result" if command == "execute_trade" else "generic_result"
                })
                return
        
        handler_map = {
            "execute_trade": self._execute_trade_action,
            "get_account_info": self._get_account_info_action,
            "get_symbol_info": self._get_symbol_info_action,
            "get_positions": self._get_positions_action,
            "ping": self._ping_action,
            "get_all_symbols": self._get_all_symbols_action,
        }

        handler = handler_map.get(command)
        if not handler:
            raise ValueError(f"收到未知命令: {command}")

        # 所有handler现在都由handle_exceptions保护
        try:
            response_payload = handler(payload)
            status = response_payload.get("status", "error")
        except Exception as e:
            logger.error(f"[{account_name}] 处理命令 '{command}' 时发生未捕获的异常: {e}", exc_info=True)
            response_payload = {"status": "error", "message": f"命令处理异常: {str(e)}"}
            status = "error"

        self.result_queue.put({
            "account_name": account_name, "status": status,
            "payload": response_payload, "correlation_id": correlation_id,
            "type": "trade_result" if command == "execute_trade" else "generic_result"
        })

    # 执行交易请求
    @handle_exceptions(category=ErrorCategory.TRANSIENT, on_error_return={"status": "error", "message": "交易执行时发生未知异常"})
    def _execute_trade_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        account_name = self.account_config.get("name")
        
        # 记录交易请求详情
        action_type = payload.get('action', 'unknown')
        symbol = payload.get('symbol', 'unknown')
        volume = payload.get('volume', 0)
        order_type = payload.get('type', -1)
        position_id = payload.get('position', 0)
        
        # 根据不同的交易类型记录不同的日志
        if action_type == TradeAction.DEAL.value:
            if position_id > 0:  # 平仓
                logger.info(f"[{account_name}] 准备发送平仓请求: 持仓ID={position_id}, 品种={symbol}, 手数={volume}")
            else:  # 开仓
                type_str = "买入" if order_type == 0 else "卖出"
                logger.info(f"[{account_name}] 准备发送开仓请求: 品种={symbol}, 类型={type_str}, 手数={volume}")
        elif action_type == TradeAction.PENDING.value:
            logger.info(f"[{account_name}] 准备发送挂单请求: 品种={symbol}, 类型={order_type}, 手数={volume}")
        elif action_type == TradeAction.SLTP.value:
            logger.info(f"[{account_name}] 准备修改止损止盈: 持仓ID={position_id}")
        elif action_type == TradeAction.REMOVE.value:
            order_id = payload.get('order', 0)
            logger.info(f"[{account_name}] 准备删除挂单: 订单ID={order_id}")
            
        # 发送订单前记录详细信息
        logger.debug(f"[{account_name}] 发送订单详情: {payload}")
        
        # 发送订单
        result = mt5.order_send(payload)
        
        if result is None:
            error_code = mt5.last_error()
            msg = f"订单发送失败，MT5返回None。错误: {error_code}"
            logger.error(f"[{account_name}] {msg}")
            return {"status": "error", "message": msg}
            
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            msg = f"交易失败: {result.comment} (代码: {result.retcode})"
            logger.error(f"[{account_name}] {msg}")
            return {"status": "error", "message": msg, "result": result._asdict()}
            
        # 成功执行
        if action_type == TradeAction.DEAL.value:
            if position_id > 0:  # 平仓
                logger.info(f"[{account_name}] 平仓成功: 持仓ID={position_id}, 成交价={result.price}")
            else:  # 开仓
                logger.info(f"[{account_name}] 开仓成功: 订单ID={result.order}, 成交价={result.price}")
        elif action_type == TradeAction.PENDING.value:
            logger.info(f"[{account_name}] 挂单成功: 订单ID={result.order}")
        elif action_type == TradeAction.SLTP.value:
            logger.info(f"[{account_name}] 修改止损止盈成功: 持仓ID={position_id}")
        elif action_type == TradeAction.REMOVE.value:
            logger.info(f"[{account_name}] 删除挂单成功: 订单ID={payload.get('order', 0)}")
            
        return {"status": "success", "message": f"交易成功，订单ID: {result.order}", "result": result._asdict()}

    # 获取账户信息
    @handle_exceptions(category=ErrorCategory.TRANSIENT, on_error_return={"status": "error", "message": "获取账户信息时发生未知异常"})
    def _get_account_info_action(self, payload: Optional[Dict] = None) -> Dict[str, Any]:
        account_name = self.account_config.get("name")
        try:
            info = mt5.account_info()
            if not info:
                return {"status": "error", "message": "无法获取账户信息"}
            
            # 返回账户信息
            return {
                "status": "success",
                "balance": info.balance,
                "equity": info.equity,
                "margin": info.margin,
                "path": mt5.terminal_info().path
            }
        except Exception as e:
            logger.error(f"[{account_name}] 获取账户信息时发生异常: {e}", exc_info=True)
            return {"status": "error", "message": f"获取账户信息时发生异常: {e}"}

    # 获取交易品种信息
    @handle_exceptions(category=ErrorCategory.TRANSIENT, on_error_return={"status": "error", "message": "获取品种信息时发生未知异常"})
    def _get_symbol_info_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        account_name = self.account_config.get("name")
        symbol = payload.get("symbol")
        if not symbol: 
            logger.error(f"[{account_name}] 请求中缺少'symbol'参数")
            return {"status": "error", "message": "请求中缺少'symbol'参数"}
            
        logger.info(f"[{account_name}] 尝试获取品种 '{symbol}' 的信息")
        
        # 添加重试与容错机制
        max_attempts = 3
        for attempt in range(max_attempts):
            # 首先尝试直接获取
            info = mt5.symbol_info(symbol)
            if info:
                info_dict = info._asdict()
                logger.info(f"[{account_name}] 成功获取品种 '{symbol}' 信息: 点值={info_dict.get('point')}, 最小手数={info_dict.get('volume_min')}")
                return {"status": "success", "info": info_dict}
            
            # 如果失败，尝试检查大小写和空格问题
            logger.warning(f"[{account_name}] 直接获取品种 '{symbol}' 信息失败 (尝试 {attempt+1}/{max_attempts})，开始智能匹配")
            
            try:
                # 获取所有可用交易品种
                all_symbols = mt5.symbols_get()
                if all_symbols:
                    # 第一阶段：尝试不区分大小写和空格的精确匹配
                    symbol_normalized = symbol.lower().replace(' ', '')
                    symbol_map = {}
                    similar_symbols = []
                    available_symbols = []
                    
                    for s in all_symbols:
                        available_symbols.append(s.name)
                        s_normalized = s.name.lower().replace(' ', '')
                        symbol_map[s_normalized] = s.name
                        
                        # 收集相似的符号以备后用
                        if symbol_normalized in s_normalized or s_normalized in symbol_normalized:
                            similar_symbols.append(s.name)
                    
                    # 检查是否有精确匹配（忽略大小写和空格）
                    if symbol_normalized in symbol_map:
                        matched_symbol = symbol_map[symbol_normalized]
                        if matched_symbol != symbol:
                            logger.info(f"[{account_name}] 找到匹配的符号，但大小写或格式不同。请求: '{symbol}', 使用: '{matched_symbol}'")
                            symbol = matched_symbol
                            
                            # 使用正确格式的符号再次尝试
                            info = mt5.symbol_info(symbol)
                            if info:
                                info_dict = info._asdict()
                                logger.info(f"[{account_name}] 成功获取品种 '{symbol}' 信息: 点值={info_dict.get('point')}, 最小手数={info_dict.get('volume_min')}")
                                return {"status": "success", "info": info_dict}
                    
                    # 第二阶段：尝试强制选择符号
                    logger.info(f"[{account_name}] 尝试强制选择品种 '{symbol}'")
                    if mt5.symbol_select(symbol, True):
                        # 等待终端同步，逐渐增加等待时间
                        wait_time = 0.2 * (attempt + 1)
                        time.sleep(wait_time)
                        info = mt5.symbol_info(symbol)
                        if info:
                            info_dict = info._asdict()
                            logger.info(f"[{account_name}] 成功强制启用并获取品种 '{symbol}' 信息")
                            return {"status": "success", "info": info_dict}
                    
                    # 第三阶段：如果仍然失败，尝试从相似符号中选择
                    if similar_symbols and attempt == max_attempts - 1:
                        # 在最后一次尝试时，选择第一个相似的符号作为备选
                        alt_symbol = similar_symbols[0]
                        logger.warning(f"[{account_name}] 无法获取品种 '{symbol}'，尝试使用相似品种: '{alt_symbol}'")
                        
                        if mt5.symbol_select(alt_symbol, True):
                            time.sleep(0.3)  # 给予终端足够时间
                            info = mt5.symbol_info(alt_symbol)
                            if info:
                                info_dict = info._asdict()
                                logger.info(f"[{account_name}] 成功使用备选品种 '{alt_symbol}' 替代 '{symbol}'")
                                return {
                                    "status": "success", 
                                    "info": info_dict, 
                                    "original_symbol": symbol, 
                                    "used_symbol": alt_symbol,
                                    "message": f"使用备选品种 '{alt_symbol}' 替代 '{symbol}'"
                                }
                    
                    if attempt == max_attempts - 1:
                        # 如果这是最后一次尝试，提供有用的错误信息
                        if similar_symbols:
                            msg = f"无法获取品种 '{symbol}' 信息，但找到了类似的品种: {', '.join(similar_symbols[:5])}"
                        else:
                            # 列出一些可用的品种作为参考
                            sample_symbols = available_symbols[:10] if len(available_symbols) > 10 else available_symbols
                            msg = f"无法获取品种 '{symbol}' 信息。可能不可用。可用品种示例: {', '.join(sample_symbols)}"
                        
                        logger.error(f"[{account_name}] {msg}")
                        return {"status": "error", "message": msg}
            
            except Exception as e:
                logger.error(f"[{account_name}] 智能匹配品种 '{symbol}' 时出错: {e}", exc_info=True)
            
            # 暂停一下再重试
            time.sleep(0.5 * (attempt + 1))
        
        # 所有尝试都失败        
        logger.error(f"[{account_name}] 经过 {max_attempts} 次尝试后获取品种 '{symbol}' 信息失败: {mt5.last_error()}")
        return {"status": "error", "message": f"获取品种 {symbol} 信息失败: {mt5.last_error()}"}

    # 获取持仓信息
    @handle_exceptions(category=ErrorCategory.TRANSIENT, on_error_return={"status": "error", "message": "获取持仓信息时发生未知异常"})
    def _get_positions_action(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ticket = payload.get("ticket")
        if ticket:
            positions = mt5.positions_get(ticket=ticket)
        else:
            positions = mt5.positions_get()
            
        if positions is not None:
            return {"status": "success", "positions": [p._asdict() for p in positions]}
        return {"status": "error", "message": f"获取持仓失败: {mt5.last_error()}"}

    # 响应ping命令，用于健康检查
    def _ping_action(self, payload: Optional[Dict] = None) -> Dict[str, Any]:
        """响应ping命令，返回工作进程状态"""
        account_name = self.account_config.get("name")
        return {
            "status": "success",
            "message": "pong",
            "account_name": account_name,
            "mt5_connected": mt5.terminal_info() is not None
        }

    def _get_all_symbols(self) -> List[str]:
        """获取所有可用品种"""
        account_name = self.account_config.get("name")
        try:
            symbols = mt5.symbols_get()
            if symbols:
                return [s.name for s in symbols if s.visible]
            else:
                logger.warning(f"[{account_name}] 获取品种列表失败")
                return []
        except Exception as e:
            logger.error(f"[{account_name}] 获取品种列表时出错: {e}")
            return []

    # 获取所有可用的交易品种
    @handle_exceptions(category=ErrorCategory.TRANSIENT, on_error_return={"status": "error", "message": "获取所有品种时发生未知异常"})
    def _get_all_symbols_action(self, payload: Optional[Dict] = None) -> Dict[str, Any]:
        account_name = self.account_config.get("name")
        try:
            symbols = self._get_all_symbols()
            if symbols is None:
                return {"status": "error", "message": "获取所有品种失败"}
            return {"status": "success", "symbols": symbols}
        except Exception as e:
            logger.error(f"[{account_name}] 获取所有品种时发生异常: {e}", exc_info=True)
            return {"status": "error", "message": f"获取所有品种时发生异常: {e}"}

    def _shutdown_mt5(self):
        """清理并关闭MT5连接"""
        account_name = self.account_config.get("name")
        try:
            if self._mt5_connected:
                mt5.shutdown()
                self._mt5_connected = False
                logger.info(f"[{account_name}] MT5连接已关闭，工作进程已停止。")
        except Exception as e:
            logger.error(f"[{account_name}] 关闭MT5连接时出错: {e}")