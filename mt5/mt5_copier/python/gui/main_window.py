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
    QSplitter, QFrame, QProgressBar, QFileDialog
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QVariant, QModelIndex, QTimer, QAbstractTableModel
)
from PyQt5.QtGui import QFont, QColor, QPalette

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
                    "保证金", "最后交易", "错误次数"
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
                
                if role == Qt.DisplayRole:
                    if col == 0: return "✓" if account.enabled else "✗"
                    elif col == 1: return account.name
                    elif col == 2: return account.connection_status
                    elif col == 3: return f"{account.balance:.2f}"
                    elif col == 4: return f"{account.equity:.2f}"
                    elif col == 5: return f"{account.margin:.2f}"
                    elif col == 6: return account.last_trade_result
                    elif col == 7: return str(account.error_count)
                        
                elif role == Qt.BackgroundRole:
                    if col == 2:
                        if account.connection_status == "已连接": return QColor(144, 238, 144)
                        elif account.connection_status == "连接中": return QColor(255, 255, 144)
                        elif "错误" in account.connection_status: return QColor(255, 182, 193)
                            
                return QVariant()

        class PositionTableModel(QAbstractTableModel):
            """持仓表格数据模型"""
            def __init__(self):
                super().__init__()
                self.positions: List[PositionData] = []
                self.headers = ["主账户品种", "主账户订单号", "主账户类型", "主账户手数", "主账户盈亏"]
                self.follower_accounts = []
            
            def set_follower_accounts(self, accounts: List[str]):
                self.follower_accounts = accounts
                self.headers = ["主账户品种", "主账户订单号", "主账户类型", "主账户手数", "主账户盈亏"]
                for account in accounts:
                    self.headers.extend([f"{account}订单号", f"{account}类型", f"{account}手数", f"{account}盈亏"])
                self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.headers) - 1)
            
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
        self.worker = CoreWorker()
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        # 连接信号和槽
        self.worker.log_received.connect(self._append_log)
        self.worker.status_updated.connect(self._update_status)
        self.worker.account_status_updated.connect(self._update_account_status)
        self.worker.positions_updated.connect(self._update_positions)
        self.worker.error_occurred.connect(self.show_error_message)
        self.worker.connection_status_changed.connect(self._update_connection_status)

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
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        
        # 标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(QFont("Arial", 10))
        
        # 创建三个主要标签页
        self.account_tab = self._create_account_tab()
        self.control_tab = self._create_control_tab()
        self.log_tab = self._create_log_tab()
        
        self.tab_widget.addTab(self.account_tab, "账户管理")
        self.tab_widget.addTab(self.control_tab, "控制与监控")
        self.tab_widget.addTab(self.log_tab, "日志")
        
        main_layout.addWidget(self.tab_widget)
        
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
        self.add_account_btn.clicked.connect(self._add_account)
        
        self.edit_account_btn = QPushButton("编辑账户")
        self.edit_account_btn.clicked.connect(self._edit_account)
        
        self.delete_account_btn = QPushButton("删除账户")
        self.delete_account_btn.clicked.connect(self._delete_account)
        
        self.refresh_status_btn = QPushButton("刷新状态")
        self.refresh_status_btn.clicked.connect(self.worker.request_status_update)

        button_layout.addWidget(self.add_account_btn)
        button_layout.addWidget(self.edit_account_btn)
        button_layout.addWidget(self.delete_account_btn)
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
        self.start_button.clicked.connect(self._toggle_trading)
        
        self.status_label = QLabel("状态: 未运行")
        self.status_label.setStyleSheet("font-weight: bold;")
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.status_label)
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
        self.clear_log_btn.clicked.connect(self._clear_logs)
        
        self.export_log_btn = QPushButton("导出日志")
        self.export_log_btn.clicked.connect(self._export_logs)
        
        button_layout.addWidget(self.clear_log_btn)
        button_layout.addWidget(self.export_log_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        return tab
        
    def _connect_signals(self):
        """连接信号和槽"""
        # 工作线程信号
        self.worker.log_received.connect(self._append_log)
        self.worker.status_updated.connect(self._update_status)
        self.worker.account_status_updated.connect(self._update_account_status)
        self.worker.positions_updated.connect(self._update_positions)
        self.worker.connection_status_changed.connect(self._update_connection_status)
        
    def _load_initial_data(self):
        """加载初始数据"""
        try:
            # 更新账户列表
            accounts = []
            for acc_config in self.config_manager.get_follower_accounts():
                accounts.append(self.AccountStatus(
                    name=acc_config.get("name", "Unknown"),
                    enabled=acc_config.get("enabled", False),
                    connection_status="未连接"
                ))
            
            self.account_table_model.update_accounts(accounts)
            
            # 设置持仓表格的跟单账户列
            follower_names = [acc.name for acc in accounts if acc.enabled]
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
        account_config = None
        for acc in self.config_manager.get_follower_accounts():
            if acc.get("name") == account_name:
                account_config = acc
                break
                
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
                
    def _toggle_trading(self):
        """切换跟单状态"""
        if self.start_button.text() == "启动跟单":
            self._start_trading()
        else:
            self._stop_trading()
            
    def _start_trading(self):
        """启动跟单服务"""
        try:
            # 检查是否有启用的账户
            enabled_accounts = [acc for acc in self.account_table_model.accounts if acc.enabled]
            if not enabled_accounts:
                QMessageBox.warning(self, "无可用账户", "没有已启用的跟单账户，请先添加并启用至少一个账户")
                return
                
            # 先更新UI，确保界面立即响应
            self.start_button.setText("停止跟单")
            self.start_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 运行中")
            
            # 确保UI更新
            QApplication.processEvents()
            
            # 调用工作线程启动服务
            self.worker.start_trading()
            
            self._append_log("跟单服务已启动")
            
        except Exception as e:
            QMessageBox.critical(self, "启动失败", str(e))
            logger.error(f"Failed to start trading: {str(e)}")
            # 如果启动失败，恢复按钮状态
            self.start_button.setText("启动跟单")
            self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 未运行")
            
    def _stop_trading(self):
        """停止跟单服务"""
        try:
            # 确认停止
            reply = QMessageBox.question(
                self, 
                "确认停止", 
                "确定要停止跟单服务吗？",
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # 先更新UI，确保界面立即响应
                self.start_button.setText("启动跟单")
                self.start_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; min-height: 40px;")
                self.status_label.setText("状态: 已停止")
                
                # 确保UI更新
                QApplication.processEvents()
                
                # 调用工作线程停止服务
                self.worker.stop_trading()
                
                self._append_log("跟单服务已停止")
                
        except Exception as e:
            QMessageBox.critical(self, "停止失败", str(e))
            logger.error(f"Failed to stop trading: {str(e)}")
            # 如果停止失败，恢复按钮状态
            self.start_button.setText("停止跟单")
            self.start_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; min-height: 40px;")
            self.status_label.setText("状态: 运行中")
            
    def _update_displays(self):
        """此方法已弃用，因为我们转向了事件驱动更新。"""
        pass
        
    def _append_log(self, message: str):
        """添加日志到日志框"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.log_text.appendPlainText(f"[{timestamp}] {message}")
        
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

    def _update_account_status(self, account_statuses: List[Dict]):
        """批量更新账户状态"""
        for status_data in account_statuses:
            name = status_data.get("name")
            for i, acc in enumerate(self.account_table_model.accounts):
                if acc.name == name:
                    acc.balance = status_data.get("balance", 0.0)
                    acc.equity = status_data.get("equity", 0.0)
                    acc.margin = status_data.get("margin", 0.0)
                    if "connection_status" in status_data:
                        acc.connection_status = status_data["connection_status"]
                    if "error_count" in status_data:
                        acc.error_count = status_data["error_count"]
                    self.account_table_model.dataChanged.emit(
                        self.account_table_model.index(i, 0),
                        self.account_table_model.index(i, 7)
                    )
                    break
                    
        # 重新计算那些不应该显示的列
        self.account_table_view.resizeColumnsToContents()
        
    def _update_positions(self, positions_data: List[Dict]):
        """更新持仓信息"""
        positions = []
        
        for pos_data in positions_data:
            position = self.PositionData(
                master_symbol=pos_data.get("master_symbol", ""),
                master_ticket=pos_data.get("master_ticket", 0),
                master_volume=pos_data.get("master_volume", 0.0),
                master_profit=pos_data.get("master_profit", 0.0),
                master_type=pos_data.get("master_type", "未知"),
                follower_positions=pos_data.get("follower_positions", {})
            )
            positions.append(position)
            
        self.position_table_model.update_positions(positions)
        
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
            default_path = os.path.join(os.getcwd(), "logs", f"tradecopy_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
            
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
        # 如果跟单服务正在运行，需要确认是否停止
        if self.start_button.text() == "停止跟单":
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
                
        # 停止工作线程
        self.worker_thread.quit()
        self.worker_thread.wait()
        
        event.accept()


def run_gui():
    """启动GUI"""
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle("Fusion")
    
    # 创建日志目录
    os.makedirs("logs", exist_ok=True)
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("logs/gui.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_gui()