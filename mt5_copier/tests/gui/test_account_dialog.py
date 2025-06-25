import pytest
from PyQt5.QtWidgets import QDialogButtonBox, QTableWidgetItem
from PyQt5.QtCore import Qt
from gui.account_dialog import AccountConfigDialog

@pytest.fixture
def account_dialog(qtbot):
    """提供一个 AccountConfigDialog 的实例，用于测试。"""
    dialog = AccountConfigDialog()
    qtbot.addWidget(dialog)
    return dialog

def test_dialog_initial_state(qtbot):
    """测试：新创建的对话框应处于正确的初始状态。"""
    dialog = AccountConfigDialog()
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "添加账户"
    assert dialog.name_edit.text() == ""
    assert dialog.strategy_combo.currentText() == "正向跟单"
    assert dialog.enabled_check.isChecked() is True

def test_dialog_with_existing_config(qtbot):
    """测试：当传入现有配置进行编辑时，对话框应正确加载所有字段。"""
    existing_config = {
        "name": "Test_Account",
        "login": 12345,
        "server": "Test-Server",
        "strategy": "reverse",
        "lot_mode": "fixed",
        "lot_value": 0.05,
        "enabled": False,
        "symbol_mapping": [{"master": "EURUSD", "follower": "EURUSD.m"}]
    }
    dialog = AccountConfigDialog(account_config=existing_config)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Test_Account"
    assert dialog.login_edit.text() == "12345"
    assert dialog.strategy_combo.currentText() == "反向跟单"
    assert dialog.lot_mode_combo.currentText() == "固定手数"
    assert dialog.lot_value_spin.value() == 0.05
    assert dialog.enabled_check.isChecked() is False
    assert dialog.symbol_mapping_table.rowCount() == 1
    assert dialog.symbol_mapping_table.item(0, 0).text() == "EURUSD"
    assert dialog.symbol_mapping_table.item(0, 1).text() == "EURUSD.m"

def test_get_config(account_dialog, qtbot):
    """测试：get_config 方法应能从界面字段中正确地收集和返回配置数据。"""
    # 1. 准备：使用 qtbot 填充对话框的各个输入字段
    qtbot.keyClicks(account_dialog.name_edit, "My_New_Account")
    qtbot.keyClicks(account_dialog.login_edit, "54321")
    qtbot.keyClicks(account_dialog.password_edit, "secret")
    qtbot.keyClicks(account_dialog.server_edit, "My-Server")
    qtbot.keyClicks(account_dialog.terminal_path_edit, "D:\\metatrader5\\v2-mt5\\terminal64.exe")
    account_dialog.strategy_combo.setCurrentText("反向跟单")
    account_dialog.lot_mode_combo.setCurrentText("手数倍数")
    account_dialog.lot_value_spin.setValue(1.5)
    account_dialog.max_slippage_spin.setValue(5)
    account_dialog.enabled_check.setChecked(True)
    # Add a symbol mapping to test its collection
    account_dialog.symbol_mapping_table.setRowCount(0) # Clear default mappings
    account_dialog.symbol_mapping_table.insertRow(0)
    account_dialog.symbol_mapping_table.setItem(0, 0, QTableWidgetItem("XAUUSD"))
    account_dialog.symbol_mapping_table.setItem(0, 1, QTableWidgetItem("GOLD"))

    # 2. 执行：调用 get_config 方法
    config = account_dialog.get_config()

    # 3. 断言：检查返回的字典是否包含了所有正确的数据
    assert config["name"] == "My_New_Account"
    assert config["login"] == 54321
    assert config["password"] == "secret"
    assert config["server"] == "My-Server"
    assert config["terminal_path"] == "D:\\metatrader5\\v2-mt5\\terminal64.exe"
    assert config["strategy"] == "reverse"
    assert config["lot_mode"] == "multiplier"
    assert config["lot_value"] == 1.5
    assert config["max_slippage_pips"] == 5
    assert config["enabled"] is True
    assert "symbol_mapping" in config
    assert config["symbol_mapping"] == [{"master": "XAUUSD", "follower": "GOLD"}]

def test_symbol_mapping_add_remove(account_dialog, qtbot):
    """测试：添加和删除交易品种映射的功能。"""
    # 1. 准备：清空初始映射表
    account_dialog.symbol_mapping_table.setRowCount(0)
    
    # 2. 执行：添加一个映射
    qtbot.mouseClick(account_dialog.add_mapping_btn, Qt.LeftButton)
    
    # 3. 断言：表格应该有一行
    assert account_dialog.symbol_mapping_table.rowCount() == 1
    
    # 4. 执行：设置映射值
    account_dialog.symbol_mapping_table.setItem(0, 0, QTableWidgetItem("USDJPY"))
    account_dialog.symbol_mapping_table.setItem(0, 1, QTableWidgetItem("USDJPY.m"))
    
    # 5. 执行：添加另一个映射
    qtbot.mouseClick(account_dialog.add_mapping_btn, Qt.LeftButton)
    account_dialog.symbol_mapping_table.setItem(1, 0, QTableWidgetItem("GBPUSD"))
    account_dialog.symbol_mapping_table.setItem(1, 1, QTableWidgetItem("GBPUSD.m"))
    
    # 6. 断言：表格应该有两行
    assert account_dialog.symbol_mapping_table.rowCount() == 2
    assert account_dialog.symbol_mapping_table.item(0, 0).text() == "USDJPY"
    assert account_dialog.symbol_mapping_table.item(1, 0).text() == "GBPUSD"
    
    # 7. 执行：选择第一行并删除
    account_dialog.symbol_mapping_table.selectRow(0)
    qtbot.mouseClick(account_dialog.remove_mapping_btn, Qt.LeftButton)
    
    # 8. 断言：表格应该只剩下第二行
    assert account_dialog.symbol_mapping_table.rowCount() == 1
    assert account_dialog.symbol_mapping_table.item(0, 0).text() == "GBPUSD"
    
    # 9. 执行：获取配置
    config = account_dialog.get_config()
    
    # 10. 断言：配置中应只有一个映射
    assert len(config["symbol_mapping"]) == 1
    assert config["symbol_mapping"][0]["master"] == "GBPUSD"
    assert config["symbol_mapping"][0]["follower"] == "GBPUSD.m"

def test_validate_symbol_mapping(account_dialog, qtbot, mocker):
    """测试：验证交易品种映射的功能，确保不允许重复的主账户品种。"""
    # 1. 准备：清空初始映射表并添加两个映射
    account_dialog.symbol_mapping_table.setRowCount(0)
    
    # 首先填写必要的账户信息以通过前面的验证
    account_dialog.name_edit.setText("Test_Account")
    account_dialog.login_edit.setText("12345")
    account_dialog.password_edit.setText("password")
    account_dialog.server_edit.setText("Test-Server")
    
    # 添加第一个映射
    qtbot.mouseClick(account_dialog.add_mapping_btn, Qt.LeftButton)
    account_dialog.symbol_mapping_table.setItem(0, 0, QTableWidgetItem("EURUSD"))
    account_dialog.symbol_mapping_table.setItem(0, 1, QTableWidgetItem("EURUSD.m"))
    
    # 添加第二个映射，使用相同的主账户品种
    qtbot.mouseClick(account_dialog.add_mapping_btn, Qt.LeftButton)
    account_dialog.symbol_mapping_table.setItem(1, 0, QTableWidgetItem("EURUSD"))
    account_dialog.symbol_mapping_table.setItem(1, 1, QTableWidgetItem("EUR_USD"))
    
    # 2. 模拟警告对话框
    mock_warning = mocker.patch('gui.account_dialog.QMessageBox.warning')
    
    # 3. 执行：点击确定按钮
    dialog_buttons = account_dialog.findChild(QDialogButtonBox)
    qtbot.mouseClick(dialog_buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
    
    # 4. 断言：应显示警告对话框，且警告消息中包含重复的品种名称
    mock_warning.assert_called_once()
    assert "EURUSD" in mock_warning.call_args[0][2]  # 警告消息中应包含重复的品种名
    
    # 5. 执行：修改第二个映射，使用不同的主账户品种
    mock_warning.reset_mock()  # 重置mock，确保下一次检查正确
    account_dialog.symbol_mapping_table.setItem(1, 0, QTableWidgetItem("GBPUSD"))
    
    # 6. 模拟对话框接受
    mock_accept = mocker.patch.object(account_dialog, 'accept')
    
    # 7. 执行：再次点击确定按钮
    qtbot.mouseClick(dialog_buttons.button(QDialogButtonBox.Ok), Qt.LeftButton)
    
    # 8. 断言：对话框应被接受
    mock_accept.assert_called_once()
    
    # 9. 执行：获取配置
    config = account_dialog.get_config()
    
    # 10. 断言：配置中应有两个不同的映射
    assert len(config["symbol_mapping"]) == 2
    assert config["symbol_mapping"][0]["master"] == "EURUSD"
    assert config["symbol_mapping"][1]["master"] == "GBPUSD"