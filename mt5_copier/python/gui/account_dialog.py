"""
MT5 Trade Copier - Account Configuration Dialog
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QDialogButtonBox,
    QPushButton, QHBoxLayout, QFileDialog, QLabel, QMessageBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt
from typing import Dict, Optional, List

class AccountConfigDialog(QDialog):

    # 初始化账户配置对话框
    def __init__(self, parent=None, account_config: Optional[Dict] = None):
        super().__init__(parent)
        self.setWindowTitle("账户配置" if account_config else "添加账户")
        self.setMinimumWidth(600)  # 增加宽度以适应新添加的表格
        self.setMinimumHeight(600)  # 增加高度以适应新添加的表格
        self.setModal(True)
        
        self.account_config = account_config or {}
        self.symbol_mappings = {}  # 品种映射字典
        
        self._setup_ui()
        self._load_config()
        
    def _setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout(self)
        
        # Basic information section
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        # Account name
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("给这个账户起个名字")
        form.addRow("账户名称:", self.name_edit)
        
        # Login & password
        self.login_edit = QLineEdit()
        self.login_edit.setPlaceholderText("MT5账号")
        form.addRow("登录账号:", self.login_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("MT5密码")
        form.addRow("密码:", self.password_edit)
        
        # Server
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("如: MetaQuotes-Demo")
        form.addRow("服务器:", self.server_edit)
        
        # MT5终端路径
        terminal_layout = QHBoxLayout()
        self.terminal_path_edit = QLineEdit()
        self.terminal_path_edit.setPlaceholderText("选择MT5终端路径 (必填)")
        self.browse_button = QPushButton("浏览...")
        self.browse_button.clicked.connect(self._browse_terminal_path)
        terminal_layout.addWidget(self.terminal_path_edit)
        terminal_layout.addWidget(self.browse_button)
        form.addRow("MT5终端路径:", terminal_layout)
        
        # Strategy section
        strategy_label = QLabel("<b>跟单策略设置</b>")
        form.addRow(strategy_label)
        
        # Copy strategy
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["正向跟单", "反向跟单"])
        self.strategy_combo.currentIndexChanged.connect(self._update_strategy_ui)
        form.addRow("跟单模式:", self.strategy_combo)
        
        # Lot size mode
        self.lot_mode_combo = QComboBox()
        self.lot_mode_combo.addItems(["固定手数", "手数倍数", "风险百分比"])
        self.lot_mode_combo.currentIndexChanged.connect(self._update_lot_ui)
        form.addRow("手数模式:", self.lot_mode_combo)
        
        # Lot value
        self.lot_value_spin = QDoubleSpinBox()
        self.lot_value_spin.setDecimals(2)
        self.lot_value_spin.setRange(0.01, 1000.0)
        self.lot_value_spin.setSingleStep(0.01)
        self.lot_value_label = QLabel("值")
        
        lot_layout = QHBoxLayout()
        lot_layout.addWidget(self.lot_value_spin)
        lot_layout.addWidget(self.lot_value_label)
        form.addRow("手数/倍数值:", lot_layout)
        
        # Copy SL/TP
        self.copy_sl_tp_check = QCheckBox("同步止损止盈")
        self.copy_sl_tp_check.setToolTip("跟随主账户的止损止盈设置")
        form.addRow("", self.copy_sl_tp_check)
        
        # Reverse SL/TP - only for reverse strategy
        self.reversed_sl_tp_layout = QHBoxLayout()
        self.copy_reversed_sl_tp_check = QCheckBox("对主账户的止损止盈进行反向操作")
        self.copy_reversed_sl_tp_check.setToolTip("例如: 主账户的止损变为副账户的止盈")
        self.reversed_sl_tp_layout.addWidget(self.copy_reversed_sl_tp_check)
        form.addRow("", self.reversed_sl_tp_layout)
        
        # Copy pending orders
        self.copy_pending_check = QCheckBox("同步挂单")
        self.copy_pending_check.setToolTip("跟随主账户的挂单")
        form.addRow("", self.copy_pending_check)
        
        # Risk settings
        risk_label = QLabel("<b>风险管理设置</b>")
        form.addRow(risk_label)
        
        # Max slippage
        self.max_slippage_spin = QSpinBox()
        self.max_slippage_spin.setRange(0, 100)
        self.max_slippage_spin.setSuffix(" 点")
        form.addRow("最大滑点:", self.max_slippage_spin)
        
        # Max latency
        self.max_latency_spin = QSpinBox()
        self.max_latency_spin.setRange(0, 5000)
        self.max_latency_spin.setSuffix(" 毫秒")
        form.addRow("最大延迟:", self.max_latency_spin)
        
        # Account enabled
        self.enabled_check = QCheckBox("启用此账户")
        form.addRow("", self.enabled_check)
        
        layout.addLayout(form)
        
        # 添加交易品种映射设置组
        self.symbol_mapping_group = QGroupBox("交易品种映射设置")
        symbol_mapping_layout = QVBoxLayout()
        
        # 说明文本
        self.mapping_info_label = QLabel(
            "设置主账户交易品种与跟单账户交易品种的映射关系。"
            "如不配置，将使用相同的品种名称。"
            "此设置对于解决品种信息获取错误非常重要。"
        )
        self.mapping_info_label.setWordWrap(True)
        symbol_mapping_layout.addWidget(self.mapping_info_label)
        
        # 映射表格
        self.symbol_mapping_table = QTableWidget(0, 2)
        self.symbol_mapping_table.setHorizontalHeaderLabels(["主账户品种", "跟单账户品种"])
        self.symbol_mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        symbol_mapping_layout.addWidget(self.symbol_mapping_table)
        
        # 按钮行
        button_row = QHBoxLayout()
        self.add_mapping_btn = QPushButton("添加映射")
        self.add_mapping_btn.clicked.connect(self._add_symbol_mapping)
        self.remove_mapping_btn = QPushButton("删除选中映射")
        self.remove_mapping_btn.clicked.connect(self._remove_symbol_mapping)
        button_row.addWidget(self.add_mapping_btn)
        button_row.addWidget(self.remove_mapping_btn)
        button_row.addStretch()
        symbol_mapping_layout.addLayout(button_row)
        
        self.symbol_mapping_group.setLayout(symbol_mapping_layout)
        layout.addWidget(self.symbol_mapping_group)
        
        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self._validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def _add_symbol_mapping(self):
        """添加一个新的品种映射行"""
        row = self.symbol_mapping_table.rowCount()
        self.symbol_mapping_table.insertRow(row)
        
        master_item = QTableWidgetItem("")
        follower_item = QTableWidgetItem("")
        
        self.symbol_mapping_table.setItem(row, 0, master_item)
        self.symbol_mapping_table.setItem(row, 1, follower_item)
        
    def _remove_symbol_mapping(self):
        """删除选中的品种映射行"""
        selected_rows = set()
        for item in self.symbol_mapping_table.selectedItems():
            selected_rows.add(item.row())
        
        # 从大到小排序，以避免删除时索引变化
        for row in sorted(selected_rows, reverse=True):
            self.symbol_mapping_table.removeRow(row)
            
    def _browse_terminal_path(self):
        """浏览并选择MT5终端路径"""
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("MT5终端 (terminal.exe);;所有文件 (*.*)")
        
        if file_dialog.exec_():
            selected_files = file_dialog.selectedFiles()
            if selected_files:
                self.terminal_path_edit.setText(selected_files[0])
            
    def _load_config(self):
        """Load configuration into UI"""
        if not self.account_config:
            # Set defaults for new account
            self.strategy_combo.setCurrentIndex(0)  # Regular
            self.lot_mode_combo.setCurrentIndex(0)  # Fixed
            self.lot_value_spin.setValue(0.01)
            self.max_slippage_spin.setValue(3)
            self.max_latency_spin.setValue(500)
            self.enabled_check.setChecked(True)  # 默认启用账户
            self.copy_sl_tp_check.setChecked(True)
            self.copy_pending_check.setChecked(True)
            self.copy_reversed_sl_tp_check.setChecked(True)
            self.terminal_path_edit.setText("")  # 默认为空
            
            # 添加一些常用的默认映射作为示例
            self.symbol_mapping_table.insertRow(0)
            self.symbol_mapping_table.setItem(0, 0, QTableWidgetItem("EURUSD"))
            self.symbol_mapping_table.setItem(0, 1, QTableWidgetItem("EURUSD"))
            
            return
        
        # Load existing configuration
        self.name_edit.setText(self.account_config.get("name", ""))
        self.login_edit.setText(str(self.account_config.get("login", "")))
        self.password_edit.setText(self.account_config.get("password", ""))
        self.server_edit.setText(self.account_config.get("server", ""))
        self.terminal_path_edit.setText(self.account_config.get("terminal_path", ""))
        
        # Strategy
        strategy = self.account_config.get("strategy", "regular")
        self.strategy_combo.setCurrentIndex(0 if strategy == "regular" else 1)
        
        # Lot mode
        lot_mode = self.account_config.get("lot_mode", "fixed")
        mode_map = {"fixed": 0, "multiplier": 1, "risk_percentage": 2}
        self.lot_mode_combo.setCurrentIndex(mode_map.get(lot_mode, 0))
        
        # Other settings
        self.lot_value_spin.setValue(self.account_config.get("lot_value", 0.01))
        self.copy_sl_tp_check.setChecked(self.account_config.get("copy_sl_tp", True))
        self.copy_reversed_sl_tp_check.setChecked(self.account_config.get("copy_reversed_sl_tp", True))
        self.copy_pending_check.setChecked(self.account_config.get("copy_pending", True))
        self.max_slippage_spin.setValue(self.account_config.get("max_slippage_pips", 3))
        self.max_latency_spin.setValue(self.account_config.get("max_latency_ms", 500))
        self.enabled_check.setChecked(self.account_config.get("enabled", True))
        
        # 加载交易品种映射
        symbol_mapping = self.account_config.get("symbol_mapping", {})
        row_idx = 0
        for master_symbol, follower_symbol in symbol_mapping.items():
            self.symbol_mapping_table.insertRow(row_idx)
            self.symbol_mapping_table.setItem(row_idx, 0, QTableWidgetItem(master_symbol))
            self.symbol_mapping_table.setItem(row_idx, 1, QTableWidgetItem(follower_symbol))
            row_idx += 1
            
        # 如果没有映射项，添加一个空行
        if row_idx == 0:
            self._add_symbol_mapping()
        
        # Update UI based on current settings
        self._update_strategy_ui(self.strategy_combo.currentIndex())
        self._update_lot_ui(self.lot_mode_combo.currentIndex())
        
    def _update_strategy_ui(self, index: int):
        """Update UI based on selected strategy"""
        is_reverse = (index == 1)
        self.copy_reversed_sl_tp_check.setEnabled(is_reverse and self.copy_sl_tp_check.isChecked())
        self.copy_reversed_sl_tp_check.setVisible(is_reverse)
    
    def _update_lot_ui(self, index: int):
        """Update UI based on selected lot mode"""
        if index in [0, 1]:  # 固定或倍数
            self.lot_value_label.setText("值")
            self.lot_value_spin.setSuffix("")
            self.lot_value_spin.setDecimals(2)
            self.lot_value_spin.setSingleStep(0.01)
        elif index == 2:  # 风险百分比
            self.lot_value_label.setText("% 的余额")
            self.lot_value_spin.setSuffix(" %")
            self.lot_value_spin.setDecimals(2)
            self.lot_value_spin.setSingleStep(0.1)
    
    def _show_warning(self, title: str, message: str, widget_to_focus):
        """显示警告信息并聚焦到指定控件"""
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText(message)
        msg_box.setWindowTitle(title)
        msg_box.exec_()
        if widget_to_focus:
            widget_to_focus.setFocus()
            
    def _validate_and_accept(self):
        """验证输入并在有效时接受对话框"""
        # 验证账户名称
        if not self.name_edit.text().strip():
            self._show_warning("验证失败", "请输入账户名称", self.name_edit)
            return
            
        if not self.login_edit.text().strip():
            self._show_warning("验证失败", "请输入登录账号", self.login_edit)
            return
            
        if not self.password_edit.text():
            self._show_warning("验证失败", "请输入密码", self.password_edit)
            return
            
        if not self.server_edit.text().strip():
            self._show_warning("验证失败", "请输入服务器", self.server_edit)
            return
            
        if not self.terminal_path_edit.text().strip():
            self._show_warning("验证失败", "请选择MT5终端路径", self.terminal_path_edit)
            return
            
        # 验证交易品种映射
        symbol_mapping = {}
        for row in range(self.symbol_mapping_table.rowCount()):
            master_symbol = self.symbol_mapping_table.item(row, 0)
            follower_symbol = self.symbol_mapping_table.item(row, 1)
            
            if master_symbol and follower_symbol:
                master_text = master_symbol.text().strip()
                follower_text = follower_symbol.text().strip()
                
                if master_text and follower_text:
                    # 验证映射项没有重复
                    if master_text in symbol_mapping:
                        self._show_warning("验证失败", f"主账户品种 '{master_text}' 有重复映射", self.symbol_mapping_table)
                        return
                    
                    symbol_mapping[master_text] = follower_text
        
        self.symbol_mappings = symbol_mapping
        self.accept()
        
    def get_config(self) -> Dict:
        """从UI控件中获取配置"""
        # 从表格中读取品种映射
        symbol_mappings = {}
        for row in range(self.symbol_mapping_table.rowCount()):
            master_item = self.symbol_mapping_table.item(row, 0)
            follower_item = self.symbol_mapping_table.item(row, 1)
            
            if master_item and follower_item:
                master_symbol = master_item.text().strip()
                follower_symbol = follower_item.text().strip()
                if master_symbol and follower_symbol:
                    symbol_mappings[master_symbol] = follower_symbol

        strategy = "regular" if self.strategy_combo.currentIndex() == 0 else "reverse"
        lot_mode_map = {0: "fixed", 1: "multiplier", 2: "risk_percentage"}
        lot_mode = lot_mode_map.get(self.lot_mode_combo.currentIndex(), "fixed")
        
        return {
            "name": self.name_edit.text(),
            "login": int(self.login_edit.text()),
            "password": self.password_edit.text(),
            "server": self.server_edit.text(),
            "terminal_path": self.terminal_path_edit.text(),
            "strategy": strategy,
            "lot_mode": lot_mode,
            "lot_value": self.lot_value_spin.value(),
            "copy_sl_tp": self.copy_sl_tp_check.isChecked(),
            "copy_reversed_sl_tp": self.copy_reversed_sl_tp_check.isChecked(),
            "copy_pending": self.copy_pending_check.isChecked(),
            "max_slippage_pips": self.max_slippage_spin.value(),
            "max_latency_ms": self.max_latency_spin.value(),
            "enabled": self.enabled_check.isChecked(),
            "symbol_mapping": symbol_mappings,
        }