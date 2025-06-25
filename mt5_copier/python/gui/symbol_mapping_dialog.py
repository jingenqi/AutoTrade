"""
MT5 Trade Copier - Symbol Mapping Dialog
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView, QMessageBox,
    QDialogButtonBox, QLineEdit, QCheckBox, QGroupBox
)
from PyQt5.QtCore import Qt
import logging
import threading
import time
import MetaTrader5 as mt5
from typing import Dict, List, Any, Optional

from core.config_manager import ConfigManager

logger = logging.getLogger("TradeCopier.GUI")

class SymbolMappingDialog(QDialog):
    """符号映射对话框，用于配置主账户和跟单账户之间的符号映射"""
    
    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.master_config = config_manager.get_master_account()
        self.follower_configs = config_manager.get_follower_accounts()
        self.mapping_data = {}
        self.master_symbols = []
        self.follower_symbols_cache = {}
        
        self.setWindowTitle("符号映射配置")
        self.setMinimumSize(800, 600)
        self._setup_ui()
        self._load_data()
        
    def _setup_ui(self):
        """设置UI组件"""
        layout = QVBoxLayout(self)
        
        # 主账户信息
        master_group = QGroupBox("主账户信息")
        master_layout = QVBoxLayout(master_group)
        
        master_info = QLabel(f"主账户: {self.master_config.get('name', '未知')}")
        master_info.setStyleSheet("font-weight: bold;")
        master_layout.addWidget(master_info)
        
        # 符号过滤
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("过滤符号:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("输入关键字过滤符号...")
        self.filter_edit.textChanged.connect(self._filter_symbols)
        filter_layout.addWidget(self.filter_edit)
        
        self.show_mapped_only = QCheckBox("仅显示已映射符号")
        self.show_mapped_only.stateChanged.connect(self._filter_symbols)
        filter_layout.addWidget(self.show_mapped_only)
        
        master_layout.addLayout(filter_layout)
        
        # 符号映射表格
        self.mapping_table = QTableWidget(0, 0)
        self.mapping_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mapping_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        master_layout.addWidget(self.mapping_table)
        
        # 账户选择
        account_layout = QHBoxLayout()
        account_layout.addWidget(QLabel("选择跟单账户:"))
        self.account_combo = QComboBox()
        for account in self.follower_configs:
            if account.get("enabled", False):
                self.account_combo.addItem(account.get("name", "未知"))
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        account_layout.addWidget(self.account_combo)
        
        # 验证按钮
        self.verify_btn = QPushButton("验证符号映射")
        self.verify_btn.clicked.connect(self._verify_mapping)
        account_layout.addWidget(self.verify_btn)
        
        master_layout.addLayout(account_layout)
        
        # 编辑区域
        edit_group = QGroupBox("编辑映射")
        edit_layout = QHBoxLayout(edit_group)
        
        edit_layout.addWidget(QLabel("主账户符号:"))
        self.master_symbol_combo = QComboBox()
        edit_layout.addWidget(self.master_symbol_combo)
        
        edit_layout.addWidget(QLabel("跟单账户符号:"))
        self.follower_symbol_combo = QComboBox()
        self.follower_symbol_combo.setEditable(True)
        edit_layout.addWidget(self.follower_symbol_combo)
        
        self.add_mapping_btn = QPushButton("添加/更新映射")
        self.add_mapping_btn.clicked.connect(self._add_mapping)
        edit_layout.addWidget(self.add_mapping_btn)
        
        self.remove_mapping_btn = QPushButton("删除映射")
        self.remove_mapping_btn.clicked.connect(self._remove_mapping)
        edit_layout.addWidget(self.remove_mapping_btn)
        
        # 底部按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._save_mapping)
        button_box.rejected.connect(self.reject)
        
        # 添加所有组件到主布局
        layout.addWidget(master_group)
        layout.addWidget(edit_group)
        layout.addWidget(button_box)
        
    def _load_data(self):
        """加载数据"""
        # 启动后台线程获取符号信息
        self.loading_label = QLabel("正在加载符号信息，请稍候...")
        self.layout().addWidget(self.loading_label)
        
        threading.Thread(target=self._load_symbols_thread, daemon=True).start()
        
    def _load_symbols_thread(self):
        """在后台线程中加载符号信息"""
        try:
            # 获取主账户符号
            master_terminal = self.master_config.get("terminal_path")
            if master_terminal and self._connect_mt5(self.master_config):
                symbols = mt5.symbols_get()
                if symbols:
                    self.master_symbols = [s.name for s in symbols]
                mt5.shutdown()
                
            # 获取第一个跟单账户的符号，用于初始显示
            if self.account_combo.count() > 0:
                account_name = self.account_combo.currentText()
                account_config = next((a for a in self.follower_configs if a.get("name") == account_name), None)
                if account_config:
                    self._load_follower_symbols(account_config)
                    
            # 更新UI
            self._update_ui_after_loading()
        except Exception as e:
            logger.error(f"加载符号信息时发生错误: {e}", exc_info=True)
            
    def _update_ui_after_loading(self):
        """符号加载完成后更新UI"""
        try:
            # 移除加载标签
            self.loading_label.setParent(None)
            self.loading_label = None
            
            # 更新主账户符号下拉框
            self.master_symbol_combo.clear()
            for symbol in sorted(self.master_symbols):
                self.master_symbol_combo.addItem(symbol)
                
            # 设置表格列
            account_name = self.account_combo.currentText() if self.account_combo.count() > 0 else ""
            self.mapping_table.setColumnCount(3)
            self.mapping_table.setHorizontalHeaderLabels(["主账户符号", f"{account_name} 符号", "状态"])
            
            # 加载当前账户的映射
            self._load_current_mapping()
        except Exception as e:
            logger.error(f"更新UI时发生错误: {e}", exc_info=True)
            
    def _load_follower_symbols(self, account_config: Dict[str, Any]) -> List[str]:
        """加载跟单账户的可用符号"""
        account_name = account_config.get("name")
        
        # 检查缓存
        if account_name in self.follower_symbols_cache:
            return self.follower_symbols_cache[account_name]
            
        symbols = []
        try:
            if self._connect_mt5(account_config):
                symbol_info = mt5.symbols_get()
                if symbol_info:
                    symbols = [s.name for s in symbol_info]
                mt5.shutdown()
                
            # 缓存结果
            self.follower_symbols_cache[account_name] = symbols
            return symbols
        except Exception as e:
            logger.error(f"加载跟单账户 {account_name} 符号时发生错误: {e}", exc_info=True)
            return []
            
    def _connect_mt5(self, account_config: Dict[str, Any]) -> bool:
        """连接到MT5终端"""
        try:
            terminal_path = account_config.get("terminal_path")
            login = account_config.get("login")
            password = account_config.get("password")
            server = account_config.get("server")
            
            if not terminal_path:
                return False
                
            # 初始化MT5
            if not mt5.initialize(path=terminal_path):
                logger.error(f"MT5初始化失败: {mt5.last_error()}")
                return False
                
            # 登录
            if not mt5.login(login=login, password=password, server=server):
                logger.error(f"MT5登录失败: {mt5.last_error()}")
                mt5.shutdown()
                return False
                
            return True
        except Exception as e:
            logger.error(f"连接MT5时发生错误: {e}", exc_info=True)
            return False
            
    def _on_account_changed(self):
        """当选择的账户改变时更新UI"""
        account_name = self.account_combo.currentText()
        if not account_name:
            return
            
        # 更新表格标题
        self.mapping_table.setHorizontalHeaderLabels(["主账户符号", f"{account_name} 符号", "状态"])
        
        # 加载账户符号
        account_config = next((a for a in self.follower_configs if a.get("name") == account_name), None)
        if account_config:
            # 如果缓存中没有，启动后台线程加载
            if account_name not in self.follower_symbols_cache:
                threading.Thread(target=lambda: self._load_follower_symbols_and_update(account_config), daemon=True).start()
            else:
                # 更新跟单符号下拉框
                self._update_follower_symbol_combo(self.follower_symbols_cache[account_name])
                
        # 加载当前账户的映射
        self._load_current_mapping()
        
    def _load_follower_symbols_and_update(self, account_config: Dict[str, Any]):
        """加载跟单账户符号并更新UI"""
        symbols = self._load_follower_symbols(account_config)
        self._update_follower_symbol_combo(symbols)
        
    def _update_follower_symbol_combo(self, symbols: List[str]):
        """更新跟单符号下拉框"""
        self.follower_symbol_combo.clear()
        for symbol in sorted(symbols):
            self.follower_symbol_combo.addItem(symbol)
            
    def _load_current_mapping(self):
        """加载当前账户的符号映射"""
        account_name = self.account_combo.currentText()
        if not account_name:
            return
            
        account_config = next((a for a in self.follower_configs if a.get("name") == account_name), None)
        if not account_config:
            return
            
        # 获取符号映射
        mapping = account_config.get("symbol_mapping", {})
        
        # 更新内部数据
        self.mapping_data = dict(mapping)
        
        # 更新表格
        self._update_mapping_table()
        
    def _update_mapping_table(self):
        """更新映射表格"""
        self.mapping_table.setRowCount(0)
        
        # 应用过滤
        filter_text = self.filter_edit.text().lower()
        show_mapped_only = self.show_mapped_only.isChecked()
        
        # 决定显示哪些符号
        symbols_to_show = []
        if show_mapped_only:
            # 只显示已映射的符号
            symbols_to_show = list(self.mapping_data.keys())
        else:
            # 显示所有主账户符号
            symbols_to_show = self.master_symbols
            
        # 应用文本过滤
        if filter_text:
            symbols_to_show = [s for s in symbols_to_show if filter_text in s.lower()]
            
        # 填充表格
        for i, master_symbol in enumerate(sorted(symbols_to_show)):
            follower_symbol = self.mapping_data.get(master_symbol, "")
            
            self.mapping_table.insertRow(i)
            self.mapping_table.setItem(i, 0, QTableWidgetItem(master_symbol))
            self.mapping_table.setItem(i, 1, QTableWidgetItem(follower_symbol))
            
            # 状态列
            status = "已映射" if follower_symbol else "未映射"
            status_item = QTableWidgetItem(status)
            status_item.setForeground(Qt.darkGreen if follower_symbol else Qt.darkRed)
            self.mapping_table.setItem(i, 2, status_item)
            
        # 连接表格选择事件
        self.mapping_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        
    def _on_table_selection_changed(self):
        """当表格选择改变时更新编辑区域"""
        selected_rows = self.mapping_table.selectionModel().selectedRows()
        if not selected_rows:
            return
            
        row = selected_rows[0].row()
        master_symbol = self.mapping_table.item(row, 0).text()
        follower_symbol = self.mapping_table.item(row, 1).text()
        
        # 设置编辑区域
        index = self.master_symbol_combo.findText(master_symbol)
        if index >= 0:
            self.master_symbol_combo.setCurrentIndex(index)
            
        if follower_symbol:
            index = self.follower_symbol_combo.findText(follower_symbol)
            if index >= 0:
                self.follower_symbol_combo.setCurrentIndex(index)
            else:
                self.follower_symbol_combo.setEditText(follower_symbol)
                
    def _filter_symbols(self):
        """应用符号过滤"""
        self._update_mapping_table()
        
    def _add_mapping(self):
        """添加或更新符号映射"""
        master_symbol = self.master_symbol_combo.currentText()
        follower_symbol = self.follower_symbol_combo.currentText()
        
        if not master_symbol:
            QMessageBox.warning(self, "警告", "请选择主账户符号")
            return
            
        # 更新映射
        self.mapping_data[master_symbol] = follower_symbol
        
        # 更新表格
        self._update_mapping_table()
        
    def _remove_mapping(self):
        """删除符号映射"""
        master_symbol = self.master_symbol_combo.currentText()
        
        if not master_symbol:
            QMessageBox.warning(self, "警告", "请选择主账户符号")
            return
            
        if master_symbol in self.mapping_data:
            del self.mapping_data[master_symbol]
            
        # 更新表格
        self._update_mapping_table()
        
    def _verify_mapping(self):
        """验证符号映射"""
        account_name = self.account_combo.currentText()
        if not account_name:
            QMessageBox.warning(self, "警告", "请选择跟单账户")
            return
            
        account_config = next((a for a in self.follower_configs if a.get("name") == account_name), None)
        if not account_config:
            QMessageBox.warning(self, "警告", "找不到跟单账户配置")
            return
            
        # 显示进度对话框
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("验证中")
        progress_dialog.setText("正在验证符号映射，请稍候...")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.show()
        
        # 在后台线程中验证
        threading.Thread(target=lambda: self._verify_mapping_thread(account_config, progress_dialog), daemon=True).start()
        
    def _verify_mapping_thread(self, account_config: Dict[str, Any], progress_dialog: QMessageBox):
        """在后台线程中验证符号映射"""
        try:
            # 连接到MT5
            if not self._connect_mt5(account_config):
                self._show_verification_result(False, "无法连接到MT5终端")
                progress_dialog.close()
                return
                
            # 验证每个映射
            results = []
            for master_symbol, follower_symbol in self.mapping_data.items():
                if not follower_symbol:
                    results.append((master_symbol, follower_symbol, False, "未映射"))
                    continue
                    
                # 检查符号是否存在
                info = mt5.symbol_info(follower_symbol)
                if not info and mt5.symbol_select(follower_symbol, True):
                    time.sleep(0.2)
                    info = mt5.symbol_info(follower_symbol)
                    
                if info:
                    results.append((master_symbol, follower_symbol, True, "可用"))
                else:
                    results.append((master_symbol, follower_symbol, False, f"不可用: {mt5.last_error()}"))
                    
            # 关闭MT5
            mt5.shutdown()
            
            # 显示结果
            self._show_verification_result(True, results)
        except Exception as e:
            logger.error(f"验证符号映射时发生错误: {e}", exc_info=True)
            self._show_verification_result(False, str(e))
        finally:
            progress_dialog.close()
            
    def _show_verification_result(self, success: bool, result):
        """显示验证结果"""
        if not success:
            QMessageBox.critical(self, "验证失败", f"验证符号映射时发生错误: {result}")
            return
            
        # 创建结果对话框
        result_dialog = QDialog(self)
        result_dialog.setWindowTitle("验证结果")
        result_dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(result_dialog)
        
        # 创建结果表格
        table = QTableWidget(len(result), 4)
        table.setHorizontalHeaderLabels(["主账户符号", "跟单账户符号", "状态", "详情"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        
        for i, (master_symbol, follower_symbol, is_valid, message) in enumerate(result):
            table.setItem(i, 0, QTableWidgetItem(master_symbol))
            table.setItem(i, 1, QTableWidgetItem(follower_symbol))
            
            status_item = QTableWidgetItem("可用" if is_valid else "不可用")
            status_item.setForeground(Qt.darkGreen if is_valid else Qt.darkRed)
            table.setItem(i, 2, status_item)
            
            table.setItem(i, 3, QTableWidgetItem(message))
            
        layout.addWidget(table)
        
        # 添加关闭按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(result_dialog.close)
        layout.addWidget(button_box)
        
        # 显示对话框
        result_dialog.exec_()
        
    def _save_mapping(self):
        """保存符号映射"""
        account_name = self.account_combo.currentText()
        if not account_name:
            QMessageBox.warning(self, "警告", "请选择跟单账户")
            return
            
        # 找到对应的账户配置
        account_index = -1
        for i, account in enumerate(self.follower_configs):
            if account.get("name") == account_name:
                account_index = i
                break
                
        if account_index < 0:
            QMessageBox.critical(self, "错误", "找不到跟单账户配置")
            return
            
        # 更新配置
        self.follower_configs[account_index]["symbol_mapping"] = dict(self.mapping_data)
        
        # 保存到配置文件
        try:
            self.config_manager.set_follower_accounts(self.follower_configs)
            self.config_manager.save_config()
            QMessageBox.information(self, "成功", "符号映射已保存")
            self.accept()
        except Exception as e:
            logger.error(f"保存符号映射时发生错误: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存符号映射时发生错误: {e}")
