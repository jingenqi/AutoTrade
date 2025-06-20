import pytest
from PyQt5.QtWidgets import QDialogButtonBox
from gui.account_dialog import AccountConfigDialog

@pytest.fixture
def account_dialog(qtbot):
    """提供一个 AccountConfigDialog 的实例，用于测试。"""
    dialog = AccountConfigDialog()
    qtbot.addWidget(dialog)
    return dialog

def test_dialog_initial_state(account_dialog):
    """测试：新创建的对话框应处于正确的初始状态。"""
    assert account_dialog.windowTitle() == "添加账户"
    assert account_dialog.name_edit.text() == ""
    assert account_dialog.strategy_combo.currentText() == "正向跟单"
    assert account_dialog.enabled_check.isChecked() is True

def test_dialog_with_existing_config(qtbot):
    """测试：当传入现有配置进行编辑时，对话框应正确加载所有字段。"""
    existing_config = {
        "name": "Test_Account",
        "login": 12345,
        "server": "Test-Server",
        "strategy": "reverse",
        "lot_mode": "fixed",
        "lot_value": 0.05,
        "enabled": False
    }
    dialog = AccountConfigDialog(account_config=existing_config)
    qtbot.addWidget(dialog)

    assert dialog.name_edit.text() == "Test_Account"
    assert dialog.login_edit.text() == "12345"
    assert dialog.strategy_combo.currentText() == "反向跟单"
    assert dialog.lot_mode_combo.currentText() == "固定手数"
    assert dialog.lot_value_spin.value() == 0.05
    assert dialog.enabled_check.isChecked() is False

def test_get_config(account_dialog, qtbot):
    """测试：get_config 方法应能从界面字段中正确地收集和返回配置数据。"""
    # 1. 准备：使用 qtbot 填充对话框的各个输入字段
    qtbot.keyClicks(account_dialog.name_edit, "My_New_Account")
    qtbot.keyClicks(account_dialog.login_edit, "54321")
    qtbot.keyClicks(account_dialog.password_edit, "secret")
    qtbot.keyClicks(account_dialog.server_edit, "My-Server")
    qtbot.keyClicks(account_dialog.mt5_path_edit, "C:\\mt5")
    account_dialog.strategy_combo.setCurrentText("反向跟单")
    account_dialog.lot_mode_combo.setCurrentText("手数倍数")
    account_dialog.lot_value_spin.setValue(1.5)
    account_dialog.max_slippage_spin.setValue(5)
    account_dialog.enabled_check.setChecked(True)

    # 2. 执行：调用 get_config 方法
    config = account_dialog.get_config()

    # 3. 断言：检查返回的字典是否包含了所有正确的数据
    assert config["name"] == "My_New_Account"
    assert config["login"] == 54321
    assert config["password"] == "secret"
    assert config["server"] == "My-Server"
    assert config["mt5_path"] == "C:\\mt5"
    assert config["strategy"] == "reverse"
    assert config["lot_mode"] == "multiplier"
    assert config["lot_value"] == 1.5
    assert config["max_slippage_pips"] == 5
    assert config["enabled"] is True 