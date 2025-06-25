"""
实时监控仪表板小部件
提供企业级的实时数据展示和监控
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QGridLayout, QFrame, QScrollArea, QProgressBar
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger("TradeCopier.GUI.Dashboard")

class MetricCard(QFrame):
    """指标卡片组件"""
    
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.Box)
        self.setStyleSheet("""
            MetricCard {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(self)
        
        # 标题
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.title_label)
        
        # 值
        self.value_label = QLabel("--")
        self.value_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        layout.addWidget(self.value_label)
        
        # 变化指示
        self.change_label = QLabel("")
        self.change_label.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.change_label)
        
        layout.addStretch()
        
    def update_value(self, value: str, change: Optional[str] = None, change_positive: bool = True):
        """更新显示值"""
        self.value_label.setText(value)
        
        if change:
            color = "#4CAF50" if change_positive else "#f44336"
            arrow = "↑" if change_positive else "↓"
            self.change_label.setText(f"{arrow} {change}")
            self.change_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        else:
            self.change_label.setText("")

class AccountStatusWidget(QGroupBox):
    """账户状态小部件"""
    
    def __init__(self, account_name: str, parent=None):
        super().__init__(f"账户: {account_name}", parent)
        self.account_name = account_name
        self._setup_ui()
        
    def _setup_ui(self):
        layout = QGridLayout(self)
        
        # 连接状态
        self.status_indicator = QLabel("●")
        self.status_indicator.setStyleSheet("color: #ccc; font-size: 16px;")
        self.status_label = QLabel("未连接")
        
        layout.addWidget(self.status_indicator, 0, 0)
        layout.addWidget(self.status_label, 0, 1)
        
        # 账户信息
        self.balance_label = QLabel("余额: --")
        self.equity_label = QLabel("净值: --")
        self.margin_label = QLabel("保证金: --")
        self.profit_label = QLabel("盈亏: --")
        
        layout.addWidget(self.balance_label, 1, 0, 1, 2)
        layout.addWidget(self.equity_label, 2, 0, 1, 2)
        layout.addWidget(self.margin_label, 3, 0, 1, 2)
        layout.addWidget(self.profit_label, 4, 0, 1, 2)
        
        # 风险指标
        self.risk_bar = QProgressBar()
        self.risk_bar.setMaximum(100)
        self.risk_bar.setTextVisible(True)
        self.risk_bar.setFormat("风险: %p%")
        layout.addWidget(self.risk_bar, 5, 0, 1, 2)
        
    def update_status(self, data: Dict[str, Any]):
        """更新账户状态"""
        # 连接状态
        status = data.get("connection_status", "未知")
        if status == "已连接":
            self.status_indicator.setStyleSheet("color: #4CAF50; font-size: 16px;")
        elif "错误" in status:
            self.status_indicator.setStyleSheet("color: #f44336; font-size: 16px;")
        else:
            self.status_indicator.setStyleSheet("color: #FFC107; font-size: 16px;")
        self.status_label.setText(status)
        
        # 账户信息
        balance = data.get("balance", 0)
        equity = data.get("equity", 0)
        margin = data.get("margin", 0)
        profit = equity - balance if balance > 0 else 0
        
        self.balance_label.setText(f"余额: {balance:,.2f}")
        self.equity_label.setText(f"净值: {equity:,.2f}")
        self.margin_label.setText(f"保证金: {margin:,.2f}")
        
        # 盈亏显示
        if profit >= 0:
            self.profit_label.setText(f"盈亏: +{profit:,.2f}")
            self.profit_label.setStyleSheet("color: #4CAF50;")
        else:
            self.profit_label.setText(f"盈亏: {profit:,.2f}")
            self.profit_label.setStyleSheet("color: #f44336;")
            
        # 风险级别（简化计算）
        risk_level = 0
        if equity > 0 and margin > 0:
            margin_level = (equity / margin) * 100
            if margin_level < 200:
                risk_level = 100 - int(margin_level / 2)
            elif margin_level < 500:
                risk_level = 50 - int((margin_level - 200) / 6)
            else:
                risk_level = 0
                
        self.risk_bar.setValue(risk_level)
        if risk_level > 70:
            self.risk_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #f44336;
                }
            """)
        elif risk_level > 40:
            self.risk_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #FFC107;
                }
            """)
        else:
            self.risk_bar.setStyleSheet("""
                QProgressBar::chunk {
                    background-color: #4CAF50;
                }
            """)

class DashboardWidget(QWidget):
    """主仪表板小部件"""
    
    refresh_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.account_widgets = {}
        self._setup_ui()
        self._setup_timer()
        
    def _setup_ui(self):
        """设置UI"""
        main_layout = QVBoxLayout(self)
        
        # 标题和刷新时间
        header_layout = QHBoxLayout()
        
        title_label = QLabel("实时监控仪表板")
        title_label.setFont(QFont("Arial", 16, QFont.Bold))
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        self.last_update_label = QLabel("最后更新: --")
        self.last_update_label.setStyleSheet("color: #666;")
        header_layout.addWidget(self.last_update_label)
        
        main_layout.addLayout(header_layout)
        
        # 主要指标卡片
        metrics_layout = QHBoxLayout()
        
        self.total_trades_card = MetricCard("总交易数")
        self.success_rate_card = MetricCard("成功率")
        self.total_profit_card = MetricCard("总盈亏")
        self.active_positions_card = MetricCard("活跃持仓")
        
        metrics_layout.addWidget(self.total_trades_card)
        metrics_layout.addWidget(self.success_rate_card)
        metrics_layout.addWidget(self.total_profit_card)
        metrics_layout.addWidget(self.active_positions_card)
        
        main_layout.addLayout(metrics_layout)
        
        # 账户状态区域
        accounts_label = QLabel("账户状态")
        accounts_label.setFont(QFont("Arial", 14, QFont.Bold))
        main_layout.addWidget(accounts_label)
        
        # 创建可滚动的账户区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(400)
        
        accounts_widget = QWidget()
        self.accounts_layout = QGridLayout(accounts_widget)
        scroll_area.setWidget(accounts_widget)
        
        main_layout.addWidget(scroll_area)
        
        # 系统状态
        system_group = QGroupBox("系统状态")
        system_layout = QGridLayout(system_group)
        
        self.ea_status_label = QLabel("EA连接: 未连接")
        self.worker_status_label = QLabel("工作进程: 0/0")
        self.last_trade_label = QLabel("最后交易: --")
        self.system_health_label = QLabel("系统健康度: --")
        
        system_layout.addWidget(self.ea_status_label, 0, 0)
        system_layout.addWidget(self.worker_status_label, 0, 1)
        system_layout.addWidget(self.last_trade_label, 1, 0)
        system_layout.addWidget(self.system_health_label, 1, 1)
        
        main_layout.addWidget(system_group)
        
        main_layout.addStretch()
        
    def _setup_timer(self):
        """设置自动刷新定时器"""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_requested.emit)
        self.refresh_timer.start(5000)  # 每5秒刷新一次
        
    def update_metrics(self, data: Dict[str, Any]):
        """更新主要指标"""
        # 更新时间
        self.last_update_label.setText(f"最后更新: {datetime.now().strftime('%H:%M:%S')}")
        
        # 总交易数
        total_trades = data.get("total_trades", 0)
        prev_trades = data.get("prev_total_trades", 0)
        trades_change = total_trades - prev_trades
        self.total_trades_card.update_value(
            str(total_trades),
            f"+{trades_change}" if trades_change > 0 else None,
            True
        )
        
        # 成功率
        success_rate = data.get("success_rate", 0)
        self.success_rate_card.update_value(
            f"{success_rate:.1f}%",
            None
        )
        
        # 总盈亏
        total_profit = data.get("total_profit", 0)
        profit_change = data.get("profit_change", 0)
        self.total_profit_card.update_value(
            f"${total_profit:,.2f}",
            f"${profit_change:+,.2f}" if profit_change != 0 else None,
            profit_change >= 0
        )
        
        # 活跃持仓
        active_positions = data.get("active_positions", 0)
        self.active_positions_card.update_value(str(active_positions))
        
    def update_accounts(self, accounts_data: List[Dict[str, Any]]):
        """更新账户状态"""
        # 清理不存在的账户小部件
        existing_names = {acc.get("name") for acc in accounts_data if acc.get("name")}
        to_remove = []
        
        for name, widget in self.account_widgets.items():
            if name not in existing_names:
                to_remove.append(name)
                
        for name in to_remove:
            widget = self.account_widgets.pop(name)
            self.accounts_layout.removeWidget(widget)
            widget.deleteLater()
            
        # 更新或创建账户小部件
        row = 0
        col = 0
        max_cols = 3
        
        for account_data in accounts_data:
            name = account_data.get("name")
            if not name:
                continue
                
            # 跳过主账户（在系统状态中显示）
            if "主账户" in name or "Master" in name:
                continue
                
            if name not in self.account_widgets:
                # 创建新的账户小部件
                widget = AccountStatusWidget(name)
                self.account_widgets[name] = widget
                self.accounts_layout.addWidget(widget, row, col)
                
            # 更新账户数据
            self.account_widgets[name].update_status(account_data)
            
            # 计算下一个位置
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
                
    def update_system_status(self, data: Dict[str, Any]):
        """更新系统状态"""
        # EA连接状态
        ea_connected = data.get("ea_connected", False)
        self.ea_status_label.setText(
            f"EA连接: {'已连接' if ea_connected else '未连接'}"
        )
        self.ea_status_label.setStyleSheet(
            f"color: {'#4CAF50' if ea_connected else '#f44336'};"
        )
        
        # 工作进程状态
        active_workers = data.get("active_workers", 0)
        total_workers = data.get("total_workers", 0)
        self.worker_status_label.setText(f"工作进程: {active_workers}/{total_workers}")
        
        # 最后交易
        last_trade_time = data.get("last_trade_time")
        if last_trade_time:
            self.last_trade_label.setText(f"最后交易: {last_trade_time}")
        else:
            self.last_trade_label.setText("最后交易: --")
            
        # 系统健康度
        health_score = data.get("health_score", 0)
        health_text = "良好"
        health_color = "#4CAF50"
        
        if health_score < 60:
            health_text = "警告"
            health_color = "#FFC107"
        elif health_score < 30:
            health_text = "异常"
            health_color = "#f44336"
            
        self.system_health_label.setText(f"系统健康度: {health_text} ({health_score}%)")
        self.system_health_label.setStyleSheet(f"color: {health_color};") 