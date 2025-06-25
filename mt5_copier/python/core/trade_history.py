"""
交易历史记录管理模块
使用SQLite数据库存储和查询历史交易
"""

import sqlite3
import threading
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger("TradeCopier.TradeHistory")

@dataclass
class TradeRecord:
    """交易记录数据类"""
    id: Optional[int] = None
    timestamp: str = ""
    master_ticket: int = 0
    master_symbol: str = ""
    master_type: str = ""  # BUY/SELL
    master_volume: float = 0.0
    master_price: float = 0.0
    master_sl: float = 0.0
    master_tp: float = 0.0
    master_profit: float = 0.0
    
    follower_account: str = ""
    follower_ticket: int = 0
    follower_symbol: str = ""
    follower_type: str = ""
    follower_volume: float = 0.0
    follower_price: float = 0.0
    follower_sl: float = 0.0
    follower_tp: float = 0.0
    follower_profit: float = 0.0
    
    trade_action: str = ""  # OPEN/CLOSE
    status: str = ""  # SUCCESS/FAILED
    error_message: str = ""
    execution_time_ms: int = 0
    
    # 额外的统计信息
    slippage_pips: float = 0.0
    commission: float = 0.0
    swap: float = 0.0

class TradeHistoryManager:
    """交易历史管理器"""
    
    def __init__(self, db_path: str = "trade_history.db"):
        self.db_path = db_path
        self.lock = threading.RLock()
        self._init_database()
        
    def _init_database(self):
        """初始化数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建交易历史表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        master_ticket INTEGER NOT NULL,
                        master_symbol TEXT NOT NULL,
                        master_type TEXT NOT NULL,
                        master_volume REAL NOT NULL,
                        master_price REAL NOT NULL,
                        master_sl REAL DEFAULT 0,
                        master_tp REAL DEFAULT 0,
                        master_profit REAL DEFAULT 0,
                        
                        follower_account TEXT NOT NULL,
                        follower_ticket INTEGER,
                        follower_symbol TEXT,
                        follower_type TEXT,
                        follower_volume REAL DEFAULT 0,
                        follower_price REAL DEFAULT 0,
                        follower_sl REAL DEFAULT 0,
                        follower_tp REAL DEFAULT 0,
                        follower_profit REAL DEFAULT 0,
                        
                        trade_action TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        execution_time_ms INTEGER DEFAULT 0,
                        
                        slippage_pips REAL DEFAULT 0,
                        commission REAL DEFAULT 0,
                        swap REAL DEFAULT 0,
                        
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # 创建索引
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_timestamp 
                    ON trade_history(timestamp)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_master_ticket 
                    ON trade_history(master_ticket)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_follower_account 
                    ON trade_history(follower_account)
                """)
                
                # 创建交易统计表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trade_statistics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL UNIQUE,
                        total_trades INTEGER DEFAULT 0,
                        successful_trades INTEGER DEFAULT 0,
                        failed_trades INTEGER DEFAULT 0,
                        total_volume REAL DEFAULT 0,
                        total_profit REAL DEFAULT 0,
                        total_commission REAL DEFAULT 0,
                        total_swap REAL DEFAULT 0,
                        avg_execution_time_ms REAL DEFAULT 0,
                        avg_slippage_pips REAL DEFAULT 0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                conn.commit()
                logger.info("交易历史数据库初始化成功")
                
        except Exception as e:
            logger.error(f"初始化数据库失败: {e}", exc_info=True)
            raise
            
    def add_trade(self, trade: TradeRecord) -> bool:
        """添加交易记录"""
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 插入交易记录
                    cursor.execute("""
                        INSERT INTO trade_history (
                            timestamp, master_ticket, master_symbol, master_type,
                            master_volume, master_price, master_sl, master_tp, master_profit,
                            follower_account, follower_ticket, follower_symbol, follower_type,
                            follower_volume, follower_price, follower_sl, follower_tp, follower_profit,
                            trade_action, status, error_message, execution_time_ms,
                            slippage_pips, commission, swap
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade.timestamp, trade.master_ticket, trade.master_symbol, trade.master_type,
                        trade.master_volume, trade.master_price, trade.master_sl, trade.master_tp, trade.master_profit,
                        trade.follower_account, trade.follower_ticket, trade.follower_symbol, trade.follower_type,
                        trade.follower_volume, trade.follower_price, trade.follower_sl, trade.follower_tp, trade.follower_profit,
                        trade.trade_action, trade.status, trade.error_message, trade.execution_time_ms,
                        trade.slippage_pips, trade.commission, trade.swap
                    ))
                    
                    # 更新统计信息
                    self._update_statistics(cursor, trade)
                    
                    conn.commit()
                    return True
                    
            except Exception as e:
                logger.error(f"添加交易记录失败: {e}", exc_info=True)
                return False
                
    def _update_statistics(self, cursor: sqlite3.Cursor, trade: TradeRecord):
        """更新统计信息"""
        date = trade.timestamp.split()[0]  # 获取日期部分
        
        # 获取或创建当日统计记录
        cursor.execute("""
            INSERT OR IGNORE INTO trade_statistics (date) VALUES (?)
        """, (date,))
        
        # 更新统计数据
        if trade.status == "SUCCESS":
            cursor.execute("""
                UPDATE trade_statistics SET
                    total_trades = total_trades + 1,
                    successful_trades = successful_trades + 1,
                    total_volume = total_volume + ?,
                    total_profit = total_profit + ?,
                    total_commission = total_commission + ?,
                    total_swap = total_swap + ?,
                    avg_execution_time_ms = (
                        (avg_execution_time_ms * successful_trades + ?) / (successful_trades + 1)
                    ),
                    avg_slippage_pips = (
                        (avg_slippage_pips * successful_trades + ?) / (successful_trades + 1)
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE date = ?
            """, (
                trade.follower_volume,
                trade.follower_profit,
                trade.commission,
                trade.swap,
                trade.execution_time_ms,
                trade.slippage_pips,
                date
            ))
        else:
            cursor.execute("""
                UPDATE trade_statistics SET
                    total_trades = total_trades + 1,
                    failed_trades = failed_trades + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE date = ?
            """, (date,))
            
    def get_trades(
        self, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        account: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000
    ) -> List[TradeRecord]:
        """查询交易记录"""
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    
                    # 构建查询条件
                    conditions = []
                    params = []
                    
                    if start_date:
                        conditions.append("timestamp >= ?")
                        params.append(start_date)
                        
                    if end_date:
                        conditions.append("timestamp <= ?")
                        params.append(end_date)
                        
                    if account:
                        conditions.append("follower_account = ?")
                        params.append(account)
                        
                    if status:
                        conditions.append("status = ?")
                        params.append(status)
                        
                    # 构建SQL
                    sql = "SELECT * FROM trade_history"
                    if conditions:
                        sql += " WHERE " + " AND ".join(conditions)
                    sql += " ORDER BY timestamp DESC LIMIT ?"
                    params.append(limit)
                    
                    # 执行查询
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    
                    # 转换为TradeRecord对象
                    trades = []
                    for row in rows:
                        trade_dict = dict(row)
                        trades.append(TradeRecord(**trade_dict))
                        
                    return trades
                    
            except Exception as e:
                logger.error(f"查询交易记录失败: {e}", exc_info=True)
                return []
                
    def get_statistics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取交易统计信息"""
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 构建查询条件
                    conditions = []
                    params = []
                    
                    if start_date:
                        conditions.append("date >= ?")
                        params.append(start_date)
                        
                    if end_date:
                        conditions.append("date <= ?")
                        params.append(end_date)
                        
                    # 查询汇总统计
                    sql = """
                        SELECT 
                            SUM(total_trades) as total_trades,
                            SUM(successful_trades) as successful_trades,
                            SUM(failed_trades) as failed_trades,
                            SUM(total_volume) as total_volume,
                            SUM(total_profit) as total_profit,
                            SUM(total_commission) as total_commission,
                            SUM(total_swap) as total_swap,
                            AVG(avg_execution_time_ms) as avg_execution_time_ms,
                            AVG(avg_slippage_pips) as avg_slippage_pips
                        FROM trade_statistics
                    """
                    
                    if conditions:
                        sql += " WHERE " + " AND ".join(conditions)
                        
                    cursor.execute(sql, params)
                    row = cursor.fetchone()
                    
                    if row and row[0]:  # 有数据
                        return {
                            "total_trades": row[0] or 0,
                            "successful_trades": row[1] or 0,
                            "failed_trades": row[2] or 0,
                            "success_rate": (row[1] / row[0] * 100) if row[0] > 0 else 0,
                            "total_volume": row[3] or 0,
                            "total_profit": row[4] or 0,
                            "total_commission": row[5] or 0,
                            "total_swap": row[6] or 0,
                            "net_profit": (row[4] or 0) - (row[5] or 0) - (row[6] or 0),
                            "avg_execution_time_ms": row[7] or 0,
                            "avg_slippage_pips": row[8] or 0
                        }
                    else:
                        return {
                            "total_trades": 0,
                            "successful_trades": 0,
                            "failed_trades": 0,
                            "success_rate": 0,
                            "total_volume": 0,
                            "total_profit": 0,
                            "total_commission": 0,
                            "total_swap": 0,
                            "net_profit": 0,
                            "avg_execution_time_ms": 0,
                            "avg_slippage_pips": 0
                        }
                        
            except Exception as e:
                logger.error(f"获取统计信息失败: {e}", exc_info=True)
                return {}
                
    def get_account_performance(self, account: str, days: int = 30) -> Dict[str, Any]:
        """获取账户表现"""
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 查询账户统计
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_trades,
                            SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) as successful_trades,
                            SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed_trades,
                            SUM(follower_volume) as total_volume,
                            SUM(follower_profit) as total_profit,
                            SUM(commission) as total_commission,
                            SUM(swap) as total_swap,
                            AVG(execution_time_ms) as avg_execution_time,
                            AVG(slippage_pips) as avg_slippage,
                            MIN(timestamp) as first_trade,
                            MAX(timestamp) as last_trade
                        FROM trade_history
                        WHERE follower_account = ? AND timestamp >= ?
                    """, (account, start_date))
                    
                    row = cursor.fetchone()
                    
                    if row and row[0] > 0:
                        return {
                            "account": account,
                            "period_days": days,
                            "total_trades": row[0],
                            "successful_trades": row[1],
                            "failed_trades": row[2],
                            "success_rate": (row[1] / row[0] * 100) if row[0] > 0 else 0,
                            "total_volume": row[3] or 0,
                            "total_profit": row[4] or 0,
                            "total_commission": row[5] or 0,
                            "total_swap": row[6] or 0,
                            "net_profit": (row[4] or 0) - (row[5] or 0) - (row[6] or 0),
                            "avg_execution_time_ms": row[7] or 0,
                            "avg_slippage_pips": row[8] or 0,
                            "first_trade": row[9],
                            "last_trade": row[10]
                        }
                    else:
                        return {
                            "account": account,
                            "period_days": days,
                            "total_trades": 0,
                            "successful_trades": 0,
                            "failed_trades": 0,
                            "success_rate": 0,
                            "total_volume": 0,
                            "total_profit": 0,
                            "total_commission": 0,
                            "total_swap": 0,
                            "net_profit": 0,
                            "avg_execution_time_ms": 0,
                            "avg_slippage_pips": 0,
                            "first_trade": None,
                            "last_trade": None
                        }
                        
            except Exception as e:
                logger.error(f"获取账户表现失败: {e}", exc_info=True)
                return {}
                
    def cleanup_old_records(self, days_to_keep: int = 90):
        """清理旧记录"""
        cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
        
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # 删除旧的交易记录
                    cursor.execute("""
                        DELETE FROM trade_history 
                        WHERE timestamp < ?
                    """, (cutoff_date,))
                    
                    deleted_trades = cursor.rowcount
                    
                    # 删除旧的统计记录
                    cursor.execute("""
                        DELETE FROM trade_statistics 
                        WHERE date < ?
                    """, (cutoff_date,))
                    
                    deleted_stats = cursor.rowcount
                    
                    conn.commit()
                    
                    logger.info(f"清理完成: 删除了 {deleted_trades} 条交易记录和 {deleted_stats} 条统计记录")
                    
                    # 压缩数据库
                    cursor.execute("VACUUM")
                    
            except Exception as e:
                logger.error(f"清理旧记录失败: {e}", exc_info=True) 