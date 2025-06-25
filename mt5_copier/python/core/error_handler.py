import logging
import traceback
import time
import functools
import json
from typing import Callable, Any, Optional, Dict, Type, Tuple
from enum import Enum
import threading

logger = logging.getLogger("TradeCopier.ErrorHandler")

# 定义通用的错误分类
class ErrorCategory(Enum):
    # 可恢复的临时性错误，通常由外部系统不稳定引起
    TRANSIENT = "transient"
    # 永久性错误，重试无法解决，需要人工干预或配置修复
    PERMANENT = "permanent"
    # 配置错误
    CONFIG = "config"
    # 输入数据校验失败
    VALIDATION = "validation"
    # 程序内部逻辑错误，表明代码存在bug
    LOGIC = "logic"

# 用于封装和记录详细错误信息的结构化类
class StructuredError:
    def __init__(self, exc: Exception, func: Callable, args: Tuple, kwargs: Dict, category: ErrorCategory, context: Optional[Dict] = None):
        self.timestamp = time.time()
        self.exception_type = exc.__class__.__name__
        self.exception_message = str(exc)
        self.traceback_str = traceback.format_exc()
        self.function_name = func.__name__
        self.function_args = args
        self.function_kwargs = self._filter_sensitive_data(kwargs.copy())
        self.category = category
        self.context = context or {}

    # 过滤掉日志中的敏感数据，如密码
    def _filter_sensitive_data(self, data: Dict) -> Dict:
        sensitive_keys = ['password', 'secret', 'token', 'key']
        for key, value in data.items():
            if any(s_key in key.lower() for s_key in sensitive_keys):
                data[key] = '********'
        return data

    # 将错误信息转换为字典格式，便于日志记录或传输
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "category": self.category.value,
            "error": {
                "type": self.exception_type,
                "message": self.exception_message,
            },
            "origin": {
                "function": self.function_name,
                "args": self.function_args,
                "kwargs": self.function_kwargs,
            },
            "context": self.context,
            "traceback": self.traceback_str,
        }
    
    # 记录结构化的错误日志
    def log(self, level: int = logging.ERROR):
        summary = (
            f"在 {self.function_name} 中发生错误 ({self.category.value}): "
            f"{self.exception_type} - {self.exception_message}"
        )
        logger.log(level, summary)
        # 以 DEBUG 级别记录完整的JSON格式错误细节，供深入调试
        logger.debug(f"错误详情: {json.dumps(self.to_dict(), indent=2, default=str)}")

# 自定义异常，用于表示一个错误已经被处理和记录过
class HandledException(Exception):
    def __init__(self, message: str, error_info: StructuredError):
        super().__init__(message)
        self.error_info = error_info

# 装饰器：为函数添加强大的异常捕获、记录和处理能力
def handle_exceptions(
    category: ErrorCategory = ErrorCategory.LOGIC,
    on_error_return: Any = None,
    re_raise: bool = False,
    context: Optional[Dict] = None
):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # 创建结构化错误并记录
                error_info = StructuredError(e, func, args, kwargs, category, context)
                error_info.log()
                
                if re_raise:
                    # 重新抛出一个已处理的异常，以便上层调用者知道它已被记录
                    raise HandledException(f"在 {func.__name__} 中发生错误", error_info) from e
                
                # 返回一个预设的默认值
                return on_error_return
        return wrapper
    return decorator

# 装饰器：为函数添加带有指数退避策略的重试逻辑
def with_retry(
    max_attempts: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 2.0,
    retry_on_exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = initial_delay
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retry_on_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"函数 '{func.__name__}' 在 {max_attempts} 次尝试后彻底失败。最终错误: {e}"
                        )
                        break
                    
                    logger.warning(
                        f"'{func.__name__}' 的第 {attempt + 1}/{max_attempts} 次尝试因 {e.__class__.__name__} 失败。 "
                        f"将在 {delay:.2f} 秒后重试。"
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
            
            if last_exception:
                raise last_exception
        return wrapper
    return decorator

# MT5错误码分类
def classify_mt5_error(retcode: int) -> Tuple[Optional[ErrorCategory], str]:
    """
    根据MQL5文档对MT5返回码进行分类
    https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
    """
    # 成功
    if retcode == 10009:  # TRADE_RETCODE_DONE
        return None, "Request completed"

    # 可重试的临时性错误
    retryable_codes = {
        10013: "Requote",
        10018: "Server is busy",
        10019: "Server is busy",
        10021: "Connection to trade server is lost",
        10024: "Not enough money to perform the operation",
        10027: "There are no prices",
        10028: "New prices came",
    }
    if retcode in retryable_codes:
        return ErrorCategory.TRANSIENT, retryable_codes[retcode]

    # 永久性或致命错误
    fatal_codes = {
        10012: "Invalid request",
        10014: "Invalid prices for the operation",
        10015: "Invalid stops for the operation",
        10016: "Invalid trade volume",
        10017: "Closing of the order or position is disabled",
        10020: "New request was sent",
        10022: "Operation is prohibited for the client",
        10023: "The order or position is frozen",
        10025: "Trade is disabled",
        10026: "The market is closed",
    }
    if retcode in fatal_codes:
        return ErrorCategory.PERMANENT, fatal_codes[retcode]

    # 逻辑错误（通常是客户端代码问题）
    logic_codes = {
        10030: "Unsupported filling type",
        10031: "No connection to the trade server",
        10033: "The operation is allowed for live accounts only",
        10034: "The limit of pending orders has been reached",
        10035: "The limit of orders and positions for the symbol has been reached",
    }
    if retcode in logic_codes:
        return ErrorCategory.LOGIC, logic_codes[retcode]
    
    return ErrorCategory.LOGIC, f"Unknown error code: {retcode}"


class TradingErrorHandler:
    def __init__(self, config_manager, status_callback: Optional[Callable[[str, str], None]] = None):
        self.config_manager = config_manager
        self.status_callback = status_callback
        self.error_counts: Dict[str, int] = {}
        self.disabled_accounts: set = set()

    def handle_trade_error(self, account_name: str, retcode: int, comment: str = "") -> bool:
        category, description = classify_mt5_error(retcode)
        
        if category is None:
            if self.error_counts.get(account_name, 0) > 0:
                logger.info(f"账户 {account_name} 的交易恢复正常。")
                self.error_counts[account_name] = 0
            return False

        full_error_msg = f"交易错误: {description} (代码: {retcode}, 注释: {comment})"
        logger.error(f"账户 {account_name} {full_error_msg}")
        if self.status_callback:
            self.status_callback(account_name, full_error_msg)

        self.error_counts[account_name] = self.error_counts.get(account_name, 0) + 1
        
        if category == ErrorCategory.PERMANENT:
            self._disable_account(account_name, f"致命错误: {description}")
            return False
            
        elif category == ErrorCategory.TRANSIENT:
            max_retries = self.config_manager.get_setting("engine.max_trade_retries", 3)
            if self.error_counts[account_name] < max_retries:
                logger.warning(f"账户 {account_name} 将重试交易 ({self.error_counts[account_name]}/{max_retries})")
                return True
            else:
                self._disable_account(account_name, f"重试次数过多 ({self.error_counts[account_name]} 次)")
                return False
                
        else: # LOGIC
            logger.critical(f"账户 {account_name} 出现逻辑错误，需要开发者干预: {description}")
            return False
            
    def _disable_account(self, account_name: str, reason: str):
        if account_name not in self.disabled_accounts:
            self.disabled_accounts.add(account_name)
            msg = f"已自动禁用账户 {account_name}，原因: {reason}"
            logger.critical(msg)
            if self.status_callback:
                self.status_callback(account_name, msg)
            
            # This logic should be carefully considered. Modifying config might not be ideal.
            # For now, it just disables it in memory.
            # A more robust solution might emit a signal to the GUI/main process to handle config changes.

    def is_account_disabled(self, account_name: str) -> bool:
        return account_name in self.disabled_accounts
        
    def reset_account_errors(self, account_name: str):
        self.error_counts[account_name] = 0
        if account_name in self.disabled_accounts:
            self.disabled_accounts.discard(account_name)
            logger.info(f"已重置账户 {account_name} 的错误状态。")


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self._state = "CLOSED"  # Can be CLOSED, OPEN, HALF_OPEN
        self._lock: Optional[threading.RLock] = None

    def __getstate__(self):
        """Custom pickling to handle the lock."""
        state = self.__dict__.copy()
        state['_lock'] = None
        return state

    def __setstate__(self, state):
        """Custom unpickling to recreate the lock."""
        self.__dict__.update(state)
        self._lock = None

    @property
    def lock(self) -> threading.RLock:
        """Lazy initializer for the lock to make it pickle-safe."""
        if self._lock is None:
            self._lock = threading.RLock()
        return self._lock

    @property
    def state(self):
        with self.lock:
            if self._state == "OPEN":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self._state = "HALF_OPEN"
            return self._state

    def record_failure(self):
        with self.lock:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self._state = "OPEN"
                self.last_failure_time = time.time()
                logger.warning(f"断路器开启: 连续失败 {self.failure_count} 次。将在 {self.recovery_timeout} 秒后尝试恢复。")

    def record_success(self):
        with self.lock:
            self.failure_count = 0
            if self._state == "HALF_OPEN":
                self._state = "CLOSED"
                logger.info("断路器已关闭，服务已恢复。")

    def call(self, func: Callable, *args, **kwargs) -> Any:
        if self.state == "OPEN":
            raise ConnectionAbortedError("断路器开启，服务暂时不可用")
        
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e
