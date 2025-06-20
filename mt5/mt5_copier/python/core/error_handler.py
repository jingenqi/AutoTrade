"""
错误处理模块 - 提供生产级别的错误处理和重试机制
"""
import logging
import time
import functools
from typing import Callable, Any, Optional, Tuple, Dict
from enum import Enum
import MetaTrader5 as mt5
import traceback

logger = logging.getLogger("TradeCopier.ErrorHandler")


class ErrorCategory(Enum):
    """错误分类"""
    FATAL = "fatal"          # 致命错误，不应重试
    RETRYABLE = "retryable"  # 可重试错误
    LOGICAL = "logical"      # 逻辑错误，需要开发者修复


# MT5错误码映射
MT5_ERROR_MAPPING = {
    # 致命错误 - 不应重试
    10019: (ErrorCategory.FATAL, "账户资金不足"),
    64: (ErrorCategory.FATAL, "账户被禁用"),
    133: (ErrorCategory.FATAL, "交易被禁用"),
    148: (ErrorCategory.FATAL, "订单数量超过限制"),
    149: (ErrorCategory.FATAL, "对冲被禁止"),
    
    # 可重试错误
    146: (ErrorCategory.RETRYABLE, "交易上下文繁忙"),
    4: (ErrorCategory.RETRYABLE, "交易服务器繁忙"),
    6: (ErrorCategory.RETRYABLE, "没有连接"),
    8: (ErrorCategory.RETRYABLE, "请求过于频繁"),
    128: (ErrorCategory.RETRYABLE, "交易超时"),
    129: (ErrorCategory.RETRYABLE, "价格已更改"),
    136: (ErrorCategory.RETRYABLE, "价格已过期"),
    
    # 逻辑错误
    130: (ErrorCategory.LOGICAL, "无效的止损/止盈"),
    131: (ErrorCategory.LOGICAL, "无效的交易量"),
    134: (ErrorCategory.LOGICAL, "资金不足"),
    4753: (ErrorCategory.LOGICAL, "持仓未找到"),
    4756: (ErrorCategory.LOGICAL, "交易请求发送失败"),
}


class RetryConfig:
    """重试配置"""
    def __init__(self, max_attempts: int = 3, initial_delay: float = 0.1,
                 max_delay: float = 2.0, exponential_base: float = 2.0):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base


def classify_mt5_error(retcode: int) -> Tuple[ErrorCategory, str]:
    """
    分类MT5错误码
    
    Args:
        retcode: MT5返回码
        
    Returns:
        (错误类别, 错误描述)
    """
    if retcode == mt5.TRADE_RETCODE_DONE:
        return None, "成功"
        
    error_info = MT5_ERROR_MAPPING.get(retcode)
    if error_info:
        return error_info
    
    # 未知错误默认为逻辑错误
    return ErrorCategory.LOGICAL, f"未知错误码: {retcode}"


def with_retry(retry_config: Optional[RetryConfig] = None,
               error_handler: Optional[Callable[[Exception], bool]] = None):
    """
    装饰器：为函数添加重试逻辑
    
    Args:
        retry_config: 重试配置
        error_handler: 自定义错误处理函数，返回True表示应该重试
    """
    if retry_config is None:
        retry_config = RetryConfig()
        
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(retry_config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # 如果有自定义错误处理器，使用它来判断是否重试
                    if error_handler and not error_handler(e):
                        raise
                    
                    # 如果是最后一次尝试，直接抛出异常
                    if attempt == retry_config.max_attempts - 1:
                        logger.error(f"{func.__name__} 在 {retry_config.max_attempts} 次尝试后失败: {e}")
                        raise
                    
                    # 计算延迟时间（指数退避）
                    delay = min(
                        retry_config.initial_delay * (retry_config.exponential_base ** attempt),
                        retry_config.max_delay
                    )
                    
                    logger.warning(f"{func.__name__} 第 {attempt + 1} 次尝试失败: {e}. "
                                 f"将在 {delay:.2f} 秒后重试...")
                    time.sleep(delay)
                    
            # 这行代码理论上不应该被执行到
            if last_exception:
                raise last_exception
                
        return wrapper
    return decorator


class TradingErrorHandler:
    """交易错误处理器"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.error_counts: Dict[str, int] = {}  # 跟踪每个账户的错误次数
        self.disabled_accounts: set = set()     # 被禁用的账户集合
        
    def handle_trade_error(self, account_name: str, retcode: int, 
                          comment: str = "") -> bool:
        """
        处理交易错误
        
        Args:
            account_name: 账户名称
            retcode: MT5返回码
            comment: 错误注释
            
        Returns:
            是否应该重试
        """
        category, description = classify_mt5_error(retcode)
        
        if category is None:  # 成功
            # 重置错误计数
            self.error_counts[account_name] = 0
            return False
            
        # 记录错误
        logger.error(f"账户 {account_name} 交易错误: {description} (代码: {retcode}). "
                    f"MT5注释: {comment}")
        
        # 增加错误计数
        self.error_counts[account_name] = self.error_counts.get(account_name, 0) + 1
        
        if category == ErrorCategory.FATAL:
            # 致命错误：禁用账户
            self._disable_account(account_name, f"{description} - {comment}")
            return False
            
        elif category == ErrorCategory.RETRYABLE:
            # 可重试错误
            max_retries = self.config_manager.get_setting("max_trade_retries", 3)
            if self.error_counts[account_name] <= max_retries:
                return True
            else:
                # 重试次数过多，暂时禁用
                self._disable_account(account_name, 
                                    f"重试次数过多 ({self.error_counts[account_name]} 次)")
                return False
                
        else:  # LOGICAL
            # 逻辑错误：记录详细信息供开发者调试
            logger.critical(f"逻辑错误需要修复 - 账户: {account_name}, "
                           f"错误: {description}, 代码: {retcode}")
            return False
            
    def _disable_account(self, account_name: str, reason: str):
        """禁用账户"""
        if account_name not in self.disabled_accounts:
            self.disabled_accounts.add(account_name)
            logger.critical(f"禁用账户 {account_name}: {reason}")
            
            # 更新配置
            follower_config = self.config_manager.get_follower_config(account_name)
            if follower_config:
                follower_config["enabled"] = False
                self.config_manager.save_config()
                
    def is_account_disabled(self, account_name: str) -> bool:
        """检查账户是否被禁用"""
        return account_name in self.disabled_accounts
        
    def reset_account_errors(self, account_name: str):
        """重置账户错误状态"""
        self.error_counts[account_name] = 0
        self.disabled_accounts.discard(account_name)
        

def safe_mt5_call(func: Callable, *args, **kwargs) -> Tuple[bool, Any, Optional[str]]:
    """
    安全地调用MT5函数
    
    Returns:
        (成功标志, 结果, 错误信息)
    """
    try:
        result = func(*args, **kwargs)
        
        # 检查是否有last_error
        error = mt5.last_error()
        if error and error[0] != 1:  # 1 表示成功
            return False, result, f"MT5错误: {error}"
            
        return True, result, None
        
    except Exception as e:
        logger.error(f"调用 {func.__name__} 时发生异常: {e}", exc_info=True)
        return False, None, str(e)


class CircuitBreaker:
    """
    断路器模式 - 防止故障扩散
    """
    def __init__(self, failure_threshold: int = 5, 
                 recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.is_open = False
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """通过断路器调用函数"""
        if self.is_open:
            # 检查是否应该尝试恢复
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.is_open = False
                self.failure_count = 0
                logger.info("断路器已关闭，尝试恢复服务")
            else:
                raise Exception("断路器开启，服务暂时不可用")
                
        try:
            result = func(*args, **kwargs)
            # 成功调用，重置失败计数
            self.failure_count = 0
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.is_open = True
                logger.error(f"断路器开启: 连续失败 {self.failure_count} 次")
                
            raise

class ErrorHandler:
    """错误处理类，提供统一的异常处理机制"""
    
    @staticmethod
    def safe_execute(func: Callable, *args, **kwargs) -> Optional[Any]:
        """安全执行函数，捕获并记录异常
        
        Args:
            func: 要执行的函数
            *args: 传递给函数的位置参数
            **kwargs: 传递给函数的关键字参数
            
        Returns:
            函数的返回值，如果发生异常则返回None
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"执行 {func.__name__} 时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            return None
            
    @classmethod
    def with_safe_callback(cls, callback_func: Callable, *args, **kwargs) -> Callable:
        """创建一个安全的回调函数
        
        Args:
            callback_func: 原始回调函数
            *args: 传递给回调的额外位置参数
            **kwargs: 传递给回调的额外关键字参数
            
        Returns:
            包装后的安全回调函数
        """
        def safe_callback(*cb_args, **cb_kwargs):
            try:
                merged_kwargs = {**kwargs, **cb_kwargs}
                return callback_func(*args, *cb_args, **merged_kwargs)
            except Exception as e:
                logger.error(f"回调 {callback_func.__name__} 执行错误: {str(e)}")
                logger.debug(traceback.format_exc())
                return None
        return safe_callback
        
    @staticmethod
    def get_error_info(e: Exception) -> Dict[str, str]:
        """获取异常的详细信息
        
        Args:
            e: 异常对象
            
        Returns:
            包含异常信息的字典
        """
        return {
            "type": e.__class__.__name__,
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        
    @staticmethod
    def format_exception(e: Exception) -> str:
        """格式化异常信息为可读字符串
        
        Args:
            e: 异常对象
            
        Returns:
            格式化后的异常信息字符串
        """
        return f"{e.__class__.__name__}: {str(e)}"