"""
风险管理模块
实现企业级的风险控制功能
"""

import threading
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import json

logger = logging.getLogger("TradeCopier.RiskManager")

@dataclass
class RiskProfile:
    """风险配置文件"""
    max_daily_loss: float = 0.0  # 每日最大亏损（金额）
    max_daily_loss_percent: float = 0.0  # 每日最大亏损（百分比）
    max_positions: int = 0  # 最大持仓数
    max_volume_per_trade: float = 0.0  # 单笔最大手数
    max_total_volume: float = 0.0  # 总持仓最大手数
    max_drawdown_percent: float = 0.0  # 最大回撤百分比
    min_free_margin_percent: float = 20.0  # 最小可用保证金百分比
    max_correlation_positions: int = 3  # 相关品种最大持仓数
    
    # 时间限制
    trading_hours: List[Tuple[str, str]] = None  # 交易时间段 [("09:00", "17:00")]
    excluded_days: List[int] = None  # 排除的星期几 [6, 0] = 周六周日
    excluded_dates: List[str] = None  # 排除的具体日期 ["2024-01-01"]
    
    # 品种限制
    allowed_symbols: List[str] = None  # 允许交易的品种
    excluded_symbols: List[str] = None  # 排除的品种
    symbol_max_volume: Dict[str, float] = None  # 每个品种的最大手数
    
    # 策略限制
    force_sl_tp: bool = False  # 强制设置止损止盈
    max_sl_pips: float = 0.0  # 最大止损点数
    min_risk_reward_ratio: float = 0.0  # 最小风险回报比
    
    def __post_init__(self):
        if self.trading_hours is None:
            self.trading_hours = []
        if self.excluded_days is None:
            self.excluded_days = []
        if self.excluded_dates is None:
            self.excluded_dates = []
        if self.allowed_symbols is None:
            self.allowed_symbols = []
        if self.excluded_symbols is None:
            self.excluded_symbols = []
        if self.symbol_max_volume is None:
            self.symbol_max_volume = {}

class RiskManager:
    """风险管理器"""
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.lock = threading.RLock()
        self.risk_profiles: Dict[str, RiskProfile] = {}
        self.daily_stats: Dict[str, Dict[str, float]] = {}
        self.peak_balance: Dict[str, float] = {}
        self._load_risk_profiles()
        
    def _load_risk_profiles(self):
        """加载风险配置"""
        try:
            # 从配置文件加载风险配置
            follower_accounts = self.config_manager.get_follower_accounts()
            for account in follower_accounts:
                account_name = account.get("name")
                if not account_name:
                    continue
                    
                risk_config = account.get("risk_profile", {})
                self.risk_profiles[account_name] = RiskProfile(**risk_config)
                
            logger.info(f"加载了 {len(self.risk_profiles)} 个账户的风险配置")
        except Exception as e:
            logger.error(f"加载风险配置失败: {e}", exc_info=True)
            
    def check_trade_allowed(
        self,
        account_name: str,
        symbol: str,
        volume: float,
        trade_type: str,
        sl: float = 0,
        tp: float = 0,
        current_positions: List[Dict] = None,
        account_info: Dict = None
    ) -> Tuple[bool, str]:
        """
        检查交易是否允许
        返回: (是否允许, 原因)
        """
        with self.lock:
            profile = self.risk_profiles.get(account_name)
            if not profile:
                return True, "未配置风险控制"
                
            # 1. 检查交易时间
            allowed, reason = self._check_trading_time(profile)
            if not allowed:
                return False, reason
                
            # 2. 检查品种限制
            allowed, reason = self._check_symbol_allowed(profile, symbol)
            if not allowed:
                return False, reason
                
            # 3. 检查手数限制
            allowed, reason = self._check_volume_limits(profile, symbol, volume, current_positions)
            if not allowed:
                return False, reason
                
            # 4. 检查持仓数限制
            if current_positions and profile.max_positions > 0:
                if len(current_positions) >= profile.max_positions:
                    return False, f"已达最大持仓数限制 ({profile.max_positions})"
                    
            # 5. 检查保证金要求
            if account_info:
                allowed, reason = self._check_margin_requirements(profile, account_info, volume)
                if not allowed:
                    return False, reason
                    
            # 6. 检查每日亏损限制
            allowed, reason = self._check_daily_loss_limit(account_name, profile, account_info)
            if not allowed:
                return False, reason
                
            # 7. 检查止损止盈要求
            if profile.force_sl_tp:
                if sl == 0 or tp == 0:
                    return False, "必须设置止损和止盈"
                    
            # 8. 检查风险回报比
            if profile.min_risk_reward_ratio > 0 and sl > 0 and tp > 0:
                # 简化计算，实际应该根据当前价格计算
                risk_reward = abs(tp) / abs(sl) if sl != 0 else 0
                if risk_reward < profile.min_risk_reward_ratio:
                    return False, f"风险回报比不足 (要求最小 {profile.min_risk_reward_ratio})"
                    
            return True, "通过所有风险检查"
            
    def _check_trading_time(self, profile: RiskProfile) -> Tuple[bool, str]:
        """检查交易时间"""
        now = datetime.now()
        
        # 检查排除的日期
        if now.strftime("%Y-%m-%d") in profile.excluded_dates:
            return False, "今日为排除交易日"
            
        # 检查排除的星期几
        if now.weekday() in profile.excluded_days:
            return False, "今日为排除交易日（星期限制）"
            
        # 检查交易时间段
        if profile.trading_hours:
            current_time = now.strftime("%H:%M")
            in_trading_hours = False
            
            for start_time, end_time in profile.trading_hours:
                if start_time <= current_time <= end_time:
                    in_trading_hours = True
                    break
                    
            if not in_trading_hours:
                return False, "当前时间不在允许交易时间内"
                
        return True, ""
        
    def _check_symbol_allowed(self, profile: RiskProfile, symbol: str) -> Tuple[bool, str]:
        """检查品种是否允许"""
        # 检查排除的品种
        if symbol in profile.excluded_symbols:
            return False, f"品种 {symbol} 在排除列表中"
            
        # 检查允许的品种（如果配置了）
        if profile.allowed_symbols and symbol not in profile.allowed_symbols:
            return False, f"品种 {symbol} 不在允许列表中"
            
        return True, ""
        
    def _check_volume_limits(
        self,
        profile: RiskProfile,
        symbol: str,
        volume: float,
        current_positions: List[Dict]
    ) -> Tuple[bool, str]:
        """检查手数限制"""
        # 检查单笔最大手数
        if profile.max_volume_per_trade > 0 and volume > profile.max_volume_per_trade:
            return False, f"手数超过单笔限制 ({profile.max_volume_per_trade})"
            
        # 检查品种特定限制
        if symbol in profile.symbol_max_volume:
            if volume > profile.symbol_max_volume[symbol]:
                return False, f"手数超过品种限制 ({profile.symbol_max_volume[symbol]})"
                
        # 检查总持仓手数
        if profile.max_total_volume > 0 and current_positions:
            total_volume = sum(pos.get('volume', 0) for pos in current_positions)
            if total_volume + volume > profile.max_total_volume:
                return False, f"总手数将超过限制 ({profile.max_total_volume})"
                
        return True, ""
        
    def _check_margin_requirements(
        self,
        profile: RiskProfile,
        account_info: Dict,
        volume: float
    ) -> Tuple[bool, str]:
        """检查保证金要求"""
        balance = account_info.get('balance', 0)
        equity = account_info.get('equity', 0)
        margin = account_info.get('margin', 0)
        free_margin = account_info.get('margin_free', equity - margin)
        
        if balance <= 0:
            return False, "账户余额为零"
            
        # 检查最小可用保证金百分比
        if equity > 0:
            free_margin_percent = (free_margin / equity) * 100
            if free_margin_percent < profile.min_free_margin_percent:
                return False, f"可用保证金不足 (当前 {free_margin_percent:.1f}%, 要求最小 {profile.min_free_margin_percent}%)"
                
        return True, ""
        
    def _check_daily_loss_limit(
        self,
        account_name: str,
        profile: RiskProfile,
        account_info: Dict
    ) -> Tuple[bool, str]:
        """检查每日亏损限制"""
        if not account_info:
            return True, ""
            
        balance = account_info.get('balance', 0)
        equity = account_info.get('equity', 0)
        
        # 获取或初始化每日统计
        today = datetime.now().strftime("%Y-%m-%d")
        if account_name not in self.daily_stats:
            self.daily_stats[account_name] = {}
            
        if today not in self.daily_stats[account_name]:
            self.daily_stats[account_name][today] = {
                'start_balance': balance,
                'current_loss': 0
            }
            
        # 计算当日亏损
        daily_stats = self.daily_stats[account_name][today]
        current_loss = daily_stats['start_balance'] - equity
        
        # 检查金额限制
        if profile.max_daily_loss > 0 and current_loss >= profile.max_daily_loss:
            return False, f"已达每日最大亏损限制 ({profile.max_daily_loss})"
            
        # 检查百分比限制
        if profile.max_daily_loss_percent > 0 and daily_stats['start_balance'] > 0:
            loss_percent = (current_loss / daily_stats['start_balance']) * 100
            if loss_percent >= profile.max_daily_loss_percent:
                return False, f"已达每日最大亏损百分比限制 ({profile.max_daily_loss_percent}%)"
                
        return True, ""
        
    def update_account_status(self, account_name: str, account_info: Dict):
        """更新账户状态"""
        with self.lock:
            balance = account_info.get('balance', 0)
            
            # 更新峰值余额（用于回撤计算）
            if account_name not in self.peak_balance:
                self.peak_balance[account_name] = balance
            else:
                self.peak_balance[account_name] = max(self.peak_balance[account_name], balance)
                
    def get_risk_status(self, account_name: str, account_info: Dict) -> Dict[str, Any]:
        """获取风险状态"""
        with self.lock:
            profile = self.risk_profiles.get(account_name)
            if not profile:
                return {"status": "未配置风险控制"}
                
            balance = account_info.get('balance', 0)
            equity = account_info.get('equity', 0)
            margin = account_info.get('margin', 0)
            free_margin = account_info.get('margin_free', equity - margin)
            
            # 计算各项指标
            status = {
                "balance": balance,
                "equity": equity,
                "margin": margin,
                "free_margin": free_margin,
                "free_margin_percent": (free_margin / equity * 100) if equity > 0 else 0,
                "margin_level": (equity / margin * 100) if margin > 0 else float('inf'),
            }
            
            # 计算回撤
            if account_name in self.peak_balance:
                peak = self.peak_balance[account_name]
                drawdown = peak - equity
                drawdown_percent = (drawdown / peak * 100) if peak > 0 else 0
                status["drawdown"] = drawdown
                status["drawdown_percent"] = drawdown_percent
                status["max_drawdown_alert"] = drawdown_percent >= profile.max_drawdown_percent if profile.max_drawdown_percent > 0 else False
                
            # 计算每日亏损
            today = datetime.now().strftime("%Y-%m-%d")
            if account_name in self.daily_stats and today in self.daily_stats[account_name]:
                daily_stats = self.daily_stats[account_name][today]
                daily_loss = daily_stats['start_balance'] - equity
                daily_loss_percent = (daily_loss / daily_stats['start_balance'] * 100) if daily_stats['start_balance'] > 0 else 0
                
                status["daily_loss"] = daily_loss
                status["daily_loss_percent"] = daily_loss_percent
                status["daily_loss_alert"] = (
                    (profile.max_daily_loss > 0 and daily_loss >= profile.max_daily_loss) or
                    (profile.max_daily_loss_percent > 0 and daily_loss_percent >= profile.max_daily_loss_percent)
                )
            else:
                status["daily_loss"] = 0
                status["daily_loss_percent"] = 0
                status["daily_loss_alert"] = False
                
            # 检查保证金警告
            status["margin_alert"] = status["free_margin_percent"] < profile.min_free_margin_percent
            
            return status
            
    def reset_daily_stats(self):
        """重置每日统计（应该在每日开始时调用）"""
        with self.lock:
            self.daily_stats.clear()
            logger.info("已重置每日风险统计")
            
    def export_risk_report(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        """导出风险报告"""
        with self.lock:
            report = {
                "timestamp": datetime.now().isoformat(),
                "accounts": {}
            }
            
            accounts = [account_name] if account_name else list(self.risk_profiles.keys())
            
            for acc in accounts:
                if acc in self.risk_profiles:
                    report["accounts"][acc] = {
                        "profile": self.risk_profiles[acc].__dict__,
                        "peak_balance": self.peak_balance.get(acc, 0),
                        "daily_stats": self.daily_stats.get(acc, {})
                    }
                    
            return report 