"""
MT5 Trade Copier - Main Window
GUI structure 
"""
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QPlainTextEdit,
    QTabWidget, QGroupBox, QCheckBox, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QLabel, QHeaderView, QDialog,
    QFormLayout, QDialogButtonBox, QMessageBox, QTableView,
    QSplitter, QFrame, QProgressBar, QFileDialog, QGridLayout
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QVariant, QModelIndex, QTimer, QAbstractTableModel, QMetaType, pyqtSlot
)
from PyQt5.QtGui import QFont, QColor, QPalette, QBrush

import json
import os
import logging
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from core.config_manager import ConfigManager
from .worker import CoreWorker
from .account_dialog import AccountConfigDialog
from .symbol_mapping_dialog import SymbolMappingDialog
from .dashboard_widget import DashboardWidget
from core.trade_history import TradeHistoryManager, TradeRecord
from core.risk_manager import RiskManager


logger = logging.getLogger("TradeCopier.GUI")


class MainWindow(QMainWindow):
    """Enhanced MT5 Trade Copier main window interface"""
    
    def __init__(self):
        super().__init__()

        # --- Define model classes inside __init__ to avoid premature Qt instantiation ---
        @dataclass
        class AccountStatus:
            """账户状态数据类"""
            name: str
            enabled: bool
            connection_status: str
            balance: float = 0.0
            equity: float = 0.0
            margin: float = 0.0
            last_trade_result: str = ""
            error_count: int = 0
            terminal_path: str = ""  # 添加终端路径字段
            # 主账户特有字段
            position_count: int = 0
            total_profit: float = 0.0

        @dataclass
        class PositionData:
            """持仓数据类"""
            master_symbol: str
            master_ticket: int
            master_volume: float
            master_profit: float
            master_type: str = "未知"  # BUY 或 SELL
            follower_positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

        class AccountTableModel(QAbstractTableModel):
            """账户表格数据模型"""
            def __init__(self):
                super().__init__()
                self.accounts: List[AccountStatus] = []
                self.headers = [
                    "启用", "账户名", "连接状态", "余额", "净值", 
                    "保证金", "最后交易", "终端路径"
                ]
            
            def update_accounts(self, accounts: List[AccountStatus]):
                self.beginResetModel()
                self.accounts = accounts
                self.endResetModel()
            
            def rowCount(self, parent=QModelIndex()):
                return len(self.accounts)
                
            def columnCount(self, parent=QModelIndex()):
                return len(self.headers)
                
            def headerData(self, section, orientation, role=Qt.DisplayRole):
                if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                    return self.headers[section]
                return QVariant()
                
            def data(self, index, role=Qt.DisplayRole):
                if not index.isValid() or index.row() >= len(self.accounts):
                    return QVariant()
                
                account = self.accounts[index.row()]
                col = index.column()
                
                # 特殊处理主账户行
                is_master = account.name == "主账户" or "Master" in account.name
                
                if role == Qt.DisplayRole:
                    if col == 0: return "✓" if account.enabled else "✗"
                    elif col == 1: return account.name
                    elif col == 2: return account.connection_status
                    elif col == 3: 
                        if is_master and hasattr(account, "position_count"):
                            return f"{account.position_count}个持仓"
                        return f"{account.balance:.2f}"
                    elif col == 4: 
                        if is_master and hasattr(account, "total_profit"):
                            return f"{account.total_profit:.2f}"
                        return f"{account.equity:.2f}"
                    elif col == 5: return f"{account.margin:.2f}"
                    elif col == 6: return account.last_trade_result
                    elif col == 7:
                        if hasattr(account, "terminal_path") and account.terminal_path:
                            return os.path.basename(account.terminal_path)
                        elif is_master:
                            return "主账户(ZMQ连接)"
                        else:
                            return "未配置终端路径"
                        
                elif role == Qt.BackgroundRole:
                    if is_master:
                        return QColor(230, 230, 250)  # 浅紫色背景标识主账户
                    elif col == 2:
                        if account.connection_status == "已连接": return QColor(144, 238, 144)
                        elif account.connection_status == "连接中": return QColor(255, 255, 144)
                        elif "错误" in account.connection_status: return QColor(255, 182, 193)
                    elif col == 4 and hasattr(account, "total_profit"):
                        if account.total_profit > 0: return QColor(144, 238, 144)
                        elif account.total_profit < 0: return QColor(255, 182, 193)
                    elif col == 7:
                        if not is_master and (not hasattr(account, "terminal_path") or not account.terminal_path):
                            return QColor(255, 255, 144)  # 黄色表示未配置终端路径
                            
                elif role == Qt.ForegroundRole:
                    if col == 4:
                        profit = 0
                        if is_master and hasattr(account, "total_profit"):
                            profit = account.total_profit
                        elif hasattr(account, "equity") and hasattr(account, "balance"):
                            profit = account.equity - account.balance
                            
                        if profit > 0: return QColor(0, 128, 0)
                        elif profit < 0: return QColor(255, 0, 0)
                            
                return QVariant()

        class PositionTableModel(QAbstractTableModel):
            """持仓表格数据模型"""
            def __init__(self):
                super().__init__()
                self.positions: List[PositionData] = []
                self.follower_accounts = []
                self._update_headers()
            
            def _update_headers(self):
                self.headers = ["主账户品种", "主账户订单号", "主账户类型", "主账户手数", "主账户盈亏"]
                for account in self.follower_accounts:
                    self.headers.extend([f"{account}订单号", f"{account}类型", f"{account}手数", f"{account}盈亏"])

            def set_follower_accounts(self, accounts: List[str]):
                self.beginResetModel()
                self.follower_accounts = accounts
                self._update_headers()
                self.endResetModel()
            
            def update_positions(self, positions: List[PositionData]):
                self.beginResetModel()
                self.positions = positions
                self.endResetModel()
            
            def rowCount(self, parent=QModelIndex()): return len(self.positions)
            def columnCount(self, parent=QModelIndex()): return len(self.headers)
                
            def headerData(self, section, orientation, role=Qt.DisplayRole):
                if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                    return self.headers[section]
                return QVariant()
                
            def data(self, index, role=Qt.DisplayRole):
                if not index.isValid() or index.row() >= len(self.positions):
                    return QVariant()
                
                position = self.positions[index.row()]
                col = index.column()
                
                if role == Qt.DisplayRole:
                    if col == 0: return position.master_symbol
                    elif col == 1: return str(position.master_ticket)
                    elif col == 2: return position.master_type
                    elif col == 3: return f"{position.master_volume:.2f}"
                    elif col == 4: return f"{position.master_profit:.2f}"
                    elif col >= 5:
                        follower_idx = (col - 5) // 4
                        data_type = (col - 5) % 4
                        if follower_idx < len(self.follower_accounts):
                            account_name = self.follower_accounts[follower_idx]
                            follower_data = position.follower_positions.get(account_name, {})
                            if data_type == 0: return str(follower_data.get('ticket', ''))
                            elif data_type == 1: return follower_data.get('type', '')
                            elif data_type == 2: return f"{follower_data.get('volume', 0.0):.2f}"
                            elif data_type == 3: return f"{follower_data.get('profit', 0.0):.2f}"
                
                elif role == Qt.BackgroundRole:
                    profit = None
                    if col == 4: profit = position.master_profit
                    elif col >= 5 and (col - 5) % 4 == 3:
                        follower_idx = (col - 5) // 4
                        if follower_idx < len(self.follower_accounts):
                            account_name = self.follower_accounts[follower_idx]
                            follower_data = position.follower_positions.get(account_name, {})
                            profit = follower_data.get('profit', 0.0)
                    if profit is not None:
                        if profit > 0: return QColor(144, 238, 144)
                        elif profit < 0: return QColor(255, 182, 193)
                        
                elif role == Qt.ForegroundRole:
                    profit = None
                    if col == 4: profit = position.master_profit
                    elif col >= 5 and (col - 5) % 4 == 3:
                        follower_idx = (col - 5) // 4
                        if follower_idx < len(self.follower_accounts):
                            account_name = self.follower_accounts[follower_idx]
                            follower_data = position.follower_positions.get(account_name, {})
                            profit = follower_data.get('profit', 0.0)
                    if profit is not None:
                        if profit > 0: return QColor(0, 128, 0)
                        elif profit < 0: return QColor(255, 0, 0)
                            
                return QVariant()

        # --- End of inner class definitions ---

        self.setWindowTitle("MT5 自动跟单系统")
        self.setGeometry(100, 100, 1200, 800)
        
        # Store the dynamically created classes
        self.AccountStatus = AccountStatus
        self.PositionData = PositionData
        self.AccountTableModel = AccountTableModel
        self.PositionTableModel = PositionTableModel
        
        # 初始化核心组件
        self.config_manager = ConfigManager("config/config.json")
        self.trade_history = TradeHistoryManager()
        self.risk_manager = RiskManager(self.config_manager)
        self.worker = CoreWorker("config/config.json")
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        # 启动工作线程
        self.worker_thread.start()

        # 初始化UI
        self._setup_ui()
        self._connect_signals()
        self._load_initial_data()
        self._append_log("程序已启动")

    def _setup_ui(self):
        """设置主UI布局"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # 标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont("Arial", 10))
        
        # 创建三个主要标签页
        self.dashboard_tab = self._create_dashboard_tab()
        self.account_tab = self._create_account_tab()
        self.control_tab = self._create_control_tab()
        self.history_tab = self._create_history_tab()
        self.risk_tab = self._create_risk_tab()
        self.log_tab = self._create_log_tab()
        
        # 添加标签页
        self.tab_widget.addTab(self.dashboard_tab, "仪表板")
        self.tab_widget.addTab(self.account_tab, "账户管理")
        self.tab_widget.addTab(self.control_tab, "控制与监控")
        self.tab_widget.addTab(self.history_tab, "交易历史")
        self.tab_widget.addTab(self.risk_tab, "风险管理")
        self.tab_widget.addTab(self.log_tab, "日志")
        
        main_layout.addWidget(self.tab_widget)
        
        # 状态栏
        self.statusBar().showMessage("系统就绪")
        
    def _create_account_tab(self):
        """创建账户管理标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 账户表格
        self.account_table_model = self.AccountTableModel()
        self.account_table_view = QTableView()
        self.account_table_view.setModel(self.account_table_model)
        self.account_table_view.setSelectionBehavior(QTableView.SelectRows)
        self.account_table_view.setSelectionMode(QTableView.SingleSelection)
        self.account_table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        layout.addWidget(self.account_table_view)
        
        # 按钮组
        button_layout = QHBoxLayout()
        
        self.add_account_btn = QPushButton("添加账户")
        self.edit_account_btn = QPushButton("编辑账户")
        self.delete_account_btn = QPushButton("删除账户")
        self.symbol_mapping_btn = QPushButton("品种映射")
        self.symbol_mapping_btn.setToolTip("配置主账户到跟单账户的品种映射")
        self.refresh_status_btn = QPushButton("刷新状态")

        button_layout.addWidget(self.add_account_btn)
        button_layout.addWidget(self.edit_account_btn)
        button_layout.addWidget(self.delete_account_btn)
        button_layout.addWidget(self.symbol_mapping_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.refresh_status_btn)
        
        layout.addLayout(button_layout)
        
        return tab
        
    def _create_control_tab(self):
        """创建控制与监控标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 控制区域
        control_group = QGroupBox("跟单控制")
        control_layout = QHBoxLayout(control_group)
        
        self.start_button = QPushButton("启动跟单")
        self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 40px;")
        
        self.status_label = QLabel("状态: 未运行")
        self.status_label.setStyleSheet("font-weight: bold;")
        
        # 添加符号映射按钮
        self.symbol_mapping_button = QPushButton("符号映射")
        self.symbol_mapping_button.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold;")
        self.symbol_mapping_button.clicked.connect(self._configure_symbol_mapping)
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.symbol_mapping_button)
        control_layout.addStretch()
        layout.addWidget(control_group)
        
        # 持仓监控区域
        positions_group = QGroupBox("实时持仓监控")
        positions_layout = QVBoxLayout(positions_group)
        
        self.position_table_model = self.PositionTableModel()
        self.position_table_view = QTableView()
        self.position_table_view.setModel(self.position_table_model)
        self.position_table_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        
        positions_layout.addWidget(self.position_table_view)
        
        layout.addWidget(positions_group)
        
        # 账户状态概览区域
        status_group = QGroupBox("账户状态概览")
        status_layout = QVBoxLayout(status_group)
        
        # 使用和账户表格相同的表格，避免重复，但高度较小
        status_table = QTableView()
        status_table.setModel(self.account_table_model)
        status_table.setMaximumHeight(200)
        status_table.setSelectionBehavior(QTableView.SelectRows)
        status_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        status_layout.addWidget(status_table)
        
        layout.addWidget(status_group)
        
        return tab
        
    def _create_log_tab(self):
        """创建日志标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 日志文本区域
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(5000)  # 限制最大行数以提高性能
        
        # 设置等宽字体以便更好地显示日志
        font = QFont("Courier New", 10)
        self.log_text.setFont(font)
        
        layout.addWidget(self.log_text)
        
        # 日志控制按钮
        button_layout = QHBoxLayout()
        
        self.clear_log_btn = QPushButton("清空日志")
        self.export_log_btn = QPushButton("导出日志")
        
        button_layout.addWidget(self.clear_log_btn)
        button_layout.addWidget(self.export_log_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        return tab
        
    def _create_dashboard_tab(self):
        """创建仪表板标签页"""
        self.dashboard_widget = DashboardWidget()
        self.dashboard_widget.refresh_requested.connect(self._update_dashboard)
        return self.dashboard_widget
        
    def _create_history_tab(self):
        """创建交易历史标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 工具栏
        toolbar = QHBoxLayout()
        
        # 日期范围选择
        toolbar.addWidget(QLabel("日期范围:"))
        self.history_start_date = QLineEdit()
        self.history_start_date.setPlaceholderText("开始日期 (YYYY-MM-DD)")
        toolbar.addWidget(self.history_start_date)
        
        self.history_end_date = QLineEdit()
        self.history_end_date.setPlaceholderText("结束日期 (YYYY-MM-DD)")
        toolbar.addWidget(self.history_end_date)
        
        # 账户筛选
        self.history_account_combo = QComboBox()
        self.history_account_combo.addItem("所有账户")
        toolbar.addWidget(self.history_account_combo)
        
        # 查询按钮
        self.query_history_btn = QPushButton("查询")
        self.query_history_btn.clicked.connect(self._query_trade_history)
        toolbar.addWidget(self.query_history_btn)
        
        # 导出按钮
        self.export_history_btn = QPushButton("导出")
        self.export_history_btn.clicked.connect(self._export_trade_history)
        toolbar.addWidget(self.export_history_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 统计信息
        stats_group = QGroupBox("交易统计")
        stats_layout = QHBoxLayout(stats_group)
        
        self.stats_labels = {
            'total': QLabel("总交易: 0"),
            'success': QLabel("成功: 0"),
            'failed': QLabel("失败: 0"),
            'volume': QLabel("总手数: 0"),
            'profit': QLabel("总盈亏: 0"),
            'commission': QLabel("手续费: 0")
        }
        
        for label in self.stats_labels.values():
            stats_layout.addWidget(label)
            
        layout.addWidget(stats_group)
        
        # 交易历史表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(12)
        self.history_table.setHorizontalHeaderLabels([
            "时间", "主账户品种", "主账户单号", "类型", "手数",
            "跟单账户", "跟单单号", "跟单手数", "状态",
            "盈亏", "滑点", "执行时间(ms)"
        ])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        
        layout.addWidget(self.history_table)
        
        return tab
        
    def _create_risk_tab(self):
        """创建风险管理标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 风险概览
        overview_group = QGroupBox("风险概览")
        overview_layout = QGridLayout(overview_group)
        
        self.risk_overview_labels = {
            'total_exposure': QLabel("总暴露: --"),
            'margin_level': QLabel("保证金水平: --"),
            'daily_loss': QLabel("今日亏损: --"),
            'max_drawdown': QLabel("最大回撤: --"),
            'risk_score': QLabel("风险评分: --"),
            'alerts': QLabel("风险警告: 0")
        }
        
        row = 0
        col = 0
        for label in self.risk_overview_labels.values():
            overview_layout.addWidget(label, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
                
        layout.addWidget(overview_group)
        
        # 账户风险详情
        self.risk_table = QTableWidget()
        self.risk_table.setColumnCount(9)
        self.risk_table.setHorizontalHeaderLabels([
            "账户", "余额", "净值", "保证金", "可用保证金",
            "保证金水平", "今日盈亏", "回撤", "风险状态"
        ])
        
        layout.addWidget(self.risk_table)
        
        # 风险控制按钮
        control_layout = QHBoxLayout()
        
        self.pause_trading_btn = QPushButton("暂停所有交易")
        self.pause_trading_btn.setStyleSheet("background-color: #FFC107;")
        self.pause_trading_btn.clicked.connect(self._pause_all_trading)
        control_layout.addWidget(self.pause_trading_btn)
        
        self.close_all_btn = QPushButton("平仓所有持仓")
        self.close_all_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.close_all_btn.clicked.connect(self._close_all_positions)
        control_layout.addWidget(self.close_all_btn)
        
        control_layout.addStretch()
        
        self.risk_settings_btn = QPushButton("风险设置")
        self.risk_settings_btn.clicked.connect(self._open_risk_settings)
        control_layout.addWidget(self.risk_settings_btn)
        
        layout.addLayout(control_layout)
        
        return tab
        
    def _connect_signals(self):
        """连接信号和槽"""
        # 工作线程信号
        self.worker.log_received.connect(self._append_log)
        self.worker.account_status_updated.connect(self.update_account_status)
        self.worker.positions_updated.connect(self._update_positions)
        self.worker.error_occurred.connect(self.show_error_message)

        # UI 控件信号
        self.start_button.clicked.connect(self._toggle_trading)
        self.add_account_btn.clicked.connect(self._add_account)
        self.edit_account_btn.clicked.connect(self._edit_account)
        self.delete_account_btn.clicked.connect(self._delete_account)
        self.symbol_mapping_button.clicked.connect(self._configure_symbol_mapping)
        self.refresh_status_btn.clicked.connect(self.worker.refresh_status)
        self.clear_log_btn.clicked.connect(self._clear_logs)
        self.export_log_btn.clicked.connect(self._export_logs)

    def _load_initial_data(self):
        """加载初始数据"""
        try:
            # 更新账户列表
            accounts = []
            
            # 首先添加主账户
            master_config = self.config_manager.get_master_account()
            if master_config:
                accounts.append(self.AccountStatus(
                    name=master_config.get("name", "Master_Account"),
                    enabled=master_config.get("enabled", True),
                    connection_status="未连接",
                    position_count=0,
                    total_profit=0.0
                ))
            
            # 然后添加跟单账户
            for acc_config in self.config_manager.get_follower_accounts():
                accounts.append(self.AccountStatus(
                    name=acc_config.get("name", "Unknown"),
                    enabled=acc_config.get("enabled", False),
                    connection_status="未连接"
                ))
            
            self.account_table_model.update_accounts(accounts)
            
            # 设置持仓表格的跟单账户列
            follower_names = [acc.name for acc in accounts if acc.enabled and acc.name != master_config.get("name", "Master_Account")]
            self.position_table_model.set_follower_accounts(follower_names)
            
            # 记录初始日志
            self._append_log("系统已初始化")
            
        except Exception as e:
            QMessageBox.critical(self, "加载配置失败", f"无法加载配置: {str(e)}")
            logger.error(f"Failed to load initial data: {str(e)}")
            
    def _add_account(self):
        """添加新账户"""
        dialog = AccountConfigDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            try:
                new_config = dialog.get_config()
                
                # 检查账户名是否已存在
                existing_accounts = self.config_manager.get_follower_accounts()
                if any(acc.get("name") == new_config["name"] for acc in existing_accounts):
                    QMessageBox.warning(self, "账户已存在", f"账户名 '{new_config['name']}' 已存在")
                    return
                    
                # 添加到配置
                self.config_manager.add_follower_account(new_config)
                self._load_initial_data()  # 重新加载数据
                self._append_log(f"添加账户 {new_config['name']}")
                
            except Exception as e:
                QMessageBox.critical(self, "添加账户失败", str(e))
                logger.error(f"Failed to add account: {str(e)}")
                
    def _edit_account(self):
        """编辑选中账户"""
        indexes = self.account_table_view.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "未选择账户", "请先选择要编辑的账户")
            return
            
        row = indexes[0].row()
        account_name = self.account_table_model.accounts[row].name
        
        # 获取账户配置
        account_config = self.config_manager.get_follower_config(account_name)
                
        if not account_config:
            QMessageBox.critical(self, "错误", f"找不到账户 {account_name} 的配置")
            return
            
        # 显示编辑对话框
        dialog = AccountConfigDialog(self, account_config)
        if dialog.exec_() == QDialog.Accepted:
            try:
                updated_config = dialog.get_config()
                
                # 更新配置
                self.config_manager.update_follower_account(account_name, updated_config)
                self._load_initial_data()  # 重新加载数据
                self._append_log(f"更新账户 {account_name} 配置")
                
            except Exception as e:
                QMessageBox.critical(self, "编辑账户失败", str(e))
                logger.error(f"Failed to edit account: {str(e)}")
                
    def _delete_account(self):
        """删除选中账户"""
        indexes = self.account_table_view.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "未选择账户", "请先选择要删除的账户")
            return
            
        row = indexes[0].row()
        account_name = self.account_table_model.accounts[row].name
        
        # 确认删除
        reply = QMessageBox.question(
            self, 
            "确认删除", 
            f"确定要删除账户 {account_name} 吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # 删除配置
                self.config_manager.remove_follower_account(account_name)
                self._load_initial_data()  # 重新加载数据
                self._append_log(f"删除账户 {account_name}")
                
            except Exception as e:
                QMessageBox.critical(self, "删除账户失败", str(e))
                logger.error(f"Failed to delete account: {str(e)}")
                
    def _configure_symbol_mapping(self):
        """配置品种映射"""
        indexes = self.account_table_view.selectedIndexes()
        if not indexes:
            QMessageBox.information(self, "未选择账户", "请先选择要配置品种映射的账户")
            return
            
        row = indexes[0].row()
        account = self.account_table_model.accounts[row]
        account_name = account.name
        
        # 检查是否是主账户
        if "主账户" in account_name or "Master" in account_name:
            QMessageBox.information(self, "提示", "主账户不需要配置品种映射")
            return
            
        # 检查账户是否已启动
        if account.connection_status == "未配置终端路径":
            QMessageBox.warning(
                self, 
                "账户未配置", 
                "请先配置账户的终端路径，然后启动跟单服务"
            )
            return
            
        # 显示品种映射对话框
        try:
            dialog = SymbolMappingDialog(self.config_manager, self)
            
            if dialog.exec_() == QDialog.Accepted:
                self._append_log(f"已更新账户 {account_name} 的品种映射")
                # 如果服务正在运行，可能需要重新加载配置
                if self.worker.is_running():
                    QMessageBox.information(
                        self,
                        "配置已更新",
                        "品种映射已更新。建议重启跟单服务以确保配置生效。"
                    )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开品种映射配置失败: {str(e)}")
            logger.error(f"Failed to open symbol mapping dialog: {e}", exc_info=True)
                
    def _toggle_trading(self):
        """切换跟单状态"""
        if self.start_button.text() == "启动跟单":
            self._start_trading()
        else:
            self._stop_trading()
            
    def _start_trading(self):
        """启动跟单服务"""
        try:
            self.start_button.setText("停止跟单")
            self.start_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 正在启动...")
            
            QApplication.processEvents()
            
            # 确保worker已设置了日志回调
            if not self.worker._gui_log_handler:
                self.worker.setup(log_callback=self.log_handler)
            
            self.worker.start_trading()
            
            self.status_label.setText("状态: 运行中")
            
            self._append_log("跟单服务已启动")
            
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))
            logger.error(f"Failed to start trading: {str(e)}")
            self.start_button.setText("启动跟单")
            self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 未运行")
            
    def _stop_trading(self):
        """停止跟单服务"""
        try:
            reply = QMessageBox.question(
                self, 
                "确认停止", 
                "确定要停止跟单服务吗？",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.start_button.setText("启动跟单")
                self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 40px;")
                self.status_label.setText("状态: 已停止")
                
                QApplication.processEvents()
                
                self.worker.stop_trading()
                
                self._append_log("跟单服务已停止")
                
        except Exception as e:
            QMessageBox.critical(self, "停止失败", str(e))
            logger.error(f"Failed to stop trading: {str(e)}")
            self.start_button.setText("停止跟单")
            self.start_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 运行中")
        
    def _append_log(self, message: str):
        """添加日志到日志框"""
        # 使用 Qt.QueuedConnection 来避免跨线程问题
        QTimer.singleShot(0, lambda: self._safe_append_log(message))
    
    def _safe_append_log(self, message: str):
        """在主线程中安全地添加日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.log_text.appendPlainText(f"[{timestamp}] {message}")
        # 自动滚动到底部
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
        
    # 添加一个新方法，用于接收和显示logger的消息
    def log_handler(self, message: str):
        """处理来自logger的消息并显示在GUI中"""
        # 只显示重要的日志信息，如交易事件、错误等
        if any(keyword in message for keyword in ["主账户", "交易成功", "交易失败", "错误", "警告", "连接", "断开"]):
            self._append_log(message)
        
    def _update_status(self, account_name: str, status: str):
        """更新账户状态"""
        for i, acc in enumerate(self.account_table_model.accounts):
            if acc.name == account_name:
                acc.last_trade_result = status
                self.account_table_model.dataChanged.emit(
                    self.account_table_model.index(i, 6),
                    self.account_table_model.index(i, 6)
                )
                break
                
    def _update_connection_status(self, account_name: str, status: str):
        """更新账户连接状态"""
        for i, acc in enumerate(self.account_table_model.accounts):
            if acc.name == account_name:
                acc.connection_status = status
                self.account_table_model.dataChanged.emit(
                    self.account_table_model.index(i, 2),
                    self.account_table_model.index(i, 2)
                )
                break

    @pyqtSlot(dict)
    def update_account_status(self, status_data: dict):
        """处理来自工作线程的账户状态更新。"""
        account_name = status_data.get("name")
        if not account_name:
            return

        for i, acc in enumerate(self.account_table_model.accounts):
            if acc.name == account_name:
                acc.connection_status = status_data.get('status', '未知')
                acc.balance = status_data.get('balance', 0.0)
                acc.equity = status_data.get('equity', 0.0)
                acc.margin = status_data.get('margin', 0.0)
                
                # 更新主账户特定字段
                if "主账户" in acc.name or "Master" in acc.name:
                    acc.position_count = status_data.get('position_count', 0)
                    acc.total_profit = status_data.get('total_profit', 0.0)
                else: # 更新跟单账户特定字段
                    acc.terminal_path = status_data.get('path', acc.terminal_path)
                
                # 触发整行更新
                self.account_table_model.dataChanged.emit(
                    self.account_table_model.index(i, 0),
                    self.account_table_model.index(i, self.account_table_model.columnCount() - 1)
                )
                return

        # 如果账户不在列表中 (例如，服务重启后)，则重新加载整个列表
        self._load_initial_data()
                
    def _update_positions(self, positions_data: List[Dict]):
        """更新持仓信息"""
        positions = []
        
        for pos_data in positions_data:
            # The data from the worker is already a dictionary, which matches the dataclass constructor
            positions.append(self.PositionData(**pos_data))
            
        self.position_table_model.update_positions(positions)
        self.position_table_view.resizeColumnsToContents()
        
    def show_error_message(self, error_type: str, message: str):
        """显示一个错误消息框并记录错误。"""
        self._append_log(f"错误 [{error_type}]: {message}")
        QMessageBox.critical(self, error_type, message)
        
    def _clear_logs(self):
        """清空日志"""
        self.log_text.clear()
        self._append_log("日志已清空")
        
    def _export_logs(self):
        """导出日志到文件"""
        try:
            logs_dir = "logs"
            os.makedirs(logs_dir, exist_ok=True)
            default_path = os.path.join(logs_dir, f"tradecopy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出日志",
                default_path,
                "文本文件 (*.txt);;所有文件 (*.*)"
            )
            
            if file_path:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.toPlainText())
                self._append_log(f"日志已导出至 {file_path}")
                
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            logger.error(f"Failed to export log: {str(e)}")
            
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.worker.is_running():
            reply = QMessageBox.question(
                self, 
                "确认退出", 
                "跟单服务正在运行，退出将停止服务。确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                try:
                    self.worker.stop_trading()
                except Exception as e:
                    logger.error(f"Error stopping trading during shutdown: {str(e)}")
            else:
                event.ignore()
                return
                
        self.worker_thread.quit()
        self.worker_thread.wait()
        
        event.accept()

    def _update_dashboard(self):
        """更新仪表板数据"""
        try:
            if not self.worker.is_running():
                return
                
            # 获取统计信息
            stats = self.trade_history.get_statistics()
            
            # 获取账户状态
            account_statuses = []
            if hasattr(self.worker, 'account_manager'):
                all_info = self.worker.account_manager.get_all_follower_info()
                for name, info in all_info.items():
                    status = {
                        "name": name,
                        "balance": info.get("balance", 0),
                        "equity": info.get("equity", 0),
                        "margin": info.get("margin", 0),
                        "connection_status": "已连接" if info else "未连接"
                    }
                    account_statuses.append(status)
                    
            # 获取持仓数
            active_positions = len(self.position_table_model.positions)
            
            # 更新指标
            metrics = {
                "total_trades": stats.get("total_trades", 0),
                "success_rate": stats.get("success_rate", 0),
                "total_profit": stats.get("total_profit", 0),
                "active_positions": active_positions,
                "prev_total_trades": getattr(self, '_prev_total_trades', 0),
                "profit_change": stats.get("total_profit", 0) - getattr(self, '_prev_total_profit', 0)
            }
            
            self.dashboard_widget.update_metrics(metrics)
            self.dashboard_widget.update_accounts(account_statuses)
            
            # 更新系统状态
            system_status = {
                "ea_connected": self.worker.zmq_listener.running if hasattr(self.worker, 'zmq_listener') else False,
                "active_workers": len([s for s in self.worker.account_manager.get_worker_status().values() if s == "运行中"]) if hasattr(self.worker, 'account_manager') else 0,
                "total_workers": len(self.worker.account_manager.get_worker_status()) if hasattr(self.worker, 'account_manager') else 0,
                "health_score": 100  # 简化计算
            }
            
            self.dashboard_widget.update_system_status(system_status)
            
            # 保存当前值用于下次比较
            self._prev_total_trades = stats.get("total_trades", 0)
            self._prev_total_profit = stats.get("total_profit", 0)
            
        except Exception as e:
            logger.error(f"更新仪表板失败: {e}", exc_info=True)
            
    def _query_trade_history(self):
        """查询交易历史"""
        try:
            # 获取查询参数
            start_date = self.history_start_date.text()
            end_date = self.history_end_date.text()
            account = self.history_account_combo.currentText()
            if account == "所有账户":
                account = None
                
            # 查询历史记录
            trades = self.trade_history.get_trades(
                start_date=start_date if start_date else None,
                end_date=end_date if end_date else None,
                account=account,
                limit=1000
            )
            
            # 更新表格
            self.history_table.setRowCount(len(trades))
            for row, trade in enumerate(trades):
                self.history_table.setItem(row, 0, QTableWidgetItem(trade.timestamp))
                self.history_table.setItem(row, 1, QTableWidgetItem(trade.master_symbol))
                self.history_table.setItem(row, 2, QTableWidgetItem(str(trade.master_ticket)))
                self.history_table.setItem(row, 3, QTableWidgetItem(trade.master_type))
                self.history_table.setItem(row, 4, QTableWidgetItem(f"{trade.master_volume:.2f}"))
                self.history_table.setItem(row, 5, QTableWidgetItem(trade.follower_account))
                self.history_table.setItem(row, 6, QTableWidgetItem(str(trade.follower_ticket)))
                self.history_table.setItem(row, 7, QTableWidgetItem(f"{trade.follower_volume:.2f}"))
                
                # 状态
                status_item = QTableWidgetItem(trade.status)
                if trade.status == "SUCCESS":
                    status_item.setBackground(QBrush(QColor(144, 238, 144)))
                else:
                    status_item.setBackground(QBrush(QColor(255, 182, 193)))
                self.history_table.setItem(row, 8, status_item)
                
                # 盈亏
                profit_item = QTableWidgetItem(f"{trade.follower_profit:.2f}")
                if trade.follower_profit >= 0:
                    profit_item.setForeground(QBrush(QColor(0, 128, 0)))
                else:
                    profit_item.setForeground(QBrush(QColor(255, 0, 0)))
                self.history_table.setItem(row, 9, profit_item)
                
                self.history_table.setItem(row, 10, QTableWidgetItem(f"{trade.slippage_pips:.1f}"))
                self.history_table.setItem(row, 11, QTableWidgetItem(str(trade.execution_time_ms)))
                
            # 更新统计
            stats = self.trade_history.get_statistics(start_date, end_date)
            self.stats_labels['total'].setText(f"总交易: {stats.get('total_trades', 0)}")
            self.stats_labels['success'].setText(f"成功: {stats.get('successful_trades', 0)}")
            self.stats_labels['failed'].setText(f"失败: {stats.get('failed_trades', 0)}")
            self.stats_labels['volume'].setText(f"总手数: {stats.get('total_volume', 0):.2f}")
            self.stats_labels['profit'].setText(f"总盈亏: {stats.get('total_profit', 0):.2f}")
            self.stats_labels['commission'].setText(f"手续费: {stats.get('total_commission', 0):.2f}")
            
        except Exception as e:
            QMessageBox.critical(self, "查询失败", str(e))
            logger.error(f"查询交易历史失败: {e}", exc_info=True)
            
    def _export_trade_history(self):
        """导出交易历史"""
        try:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出交易历史",
                f"trade_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV文件 (*.csv);;所有文件 (*.*)"
            )
            
            if file_path:
                # TODO: 实现CSV导出
                QMessageBox.information(self, "导出成功", f"交易历史已导出至: {file_path}")
                
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
            
    def _update_risk_overview(self):
        """更新风险概览"""
        try:
            # TODO: 实现风险概览更新
            pass
        except Exception as e:
            logger.error(f"更新风险概览失败: {e}", exc_info=True)
            
    def _pause_all_trading(self):
        """暂停所有交易"""
        reply = QMessageBox.question(
            self,
            "确认暂停",
            "确定要暂停所有跟单交易吗？\n这将阻止新的跟单操作，但不会影响现有持仓。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # TODO: 实现暂停逻辑
            self.pause_trading_btn.setText("恢复交易")
            self.pause_trading_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            self._append_log("已暂停所有跟单交易")
            
    def _close_all_positions(self):
        """平仓所有持仓"""
        reply = QMessageBox.question(
            self,
            "确认平仓",
            "警告：这将平仓所有跟单账户的所有持仓！\n\n确定要继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 二次确认
            confirm_reply = QMessageBox.warning(
                self,
                "最终确认",
                "这是最后的确认！\n\n真的要平仓所有持仓吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if confirm_reply == QMessageBox.Yes:
                # TODO: 实现平仓所有持仓的逻辑
                self._append_log("正在平仓所有持仓...")
                
    def _open_risk_settings(self):
        """打开风险设置对话框"""
        # TODO: 实现风险设置对话框
        QMessageBox.information(self, "提示", "风险设置功能正在开发中")

def run_gui():
    """启动GUI"""
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    
    os.makedirs("logs", exist_ok=True)
    
    # 配置日志系统
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/gui.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    # 设置ZmqListener和TradeEngine的日志级别为INFO，确保能捕获交易事件
    logging.getLogger("TradeCopier.ZmqListener").setLevel(logging.INFO)
    logging.getLogger("TradeCopier.core.trade_engine").setLevel(logging.INFO)
    
    # 注册Qt元类型，解决跨线程信号传递问题
    QMetaType.type("QTextBlock")
    QMetaType.type("QTextCursor")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_gui()