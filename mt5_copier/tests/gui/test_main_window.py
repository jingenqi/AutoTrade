import pytest
from unittest.mock import patch, MagicMock, call
from PyQt5.QtCore import Qt, QModelIndex
from PyQt5.QtWidgets import QMessageBox, QTableView

# Import after patching is set up
# from gui.main_window import MainWindow

@pytest.fixture
def main_window(qtbot):
    """Provides a MainWindow instance for testing, mocking the background worker."""
    # Patch CoreWorker where it's imported in main_window
    with patch('gui.main_window.CoreWorker') as mock_worker:
        from gui.main_window import MainWindow
        window = MainWindow()
        qtbot.addWidget(window)
        yield window

def test_main_window_initialization(main_window):
    """Test if the main window initializes correctly."""
    assert main_window.windowTitle() == "MT5 自动跟单系统"
    # Verify that the main components exist
    assert main_window.config_manager is not None
    assert main_window.account_table_view is not None
    assert main_window.position_table_view is not None
    assert main_window.log_text is not None

def test_start_stop_buttons(main_window, qtbot):
    """Test the functionality of the start and stop buttons."""
    # The worker's methods are mocked, so we test if they are called
    main_window.worker.start_trading = MagicMock()
    main_window.worker.stop_trading = MagicMock()

    # We need to mock QMessageBox to auto-accept the confirmation dialogs
    with patch('gui.main_window.QMessageBox.question', return_value=QMessageBox.Yes):
        # Click the button to start trading
        qtbot.mouseClick(main_window.start_button, Qt.LeftButton)
        main_window.worker.start_trading.assert_called_once()
        assert main_window.start_button.text() == "停止跟单"

        # Click the same button again to stop trading
        qtbot.mouseClick(main_window.start_button, Qt.LeftButton)
        main_window.worker.stop_trading.assert_called_once()
        assert main_window.start_button.text() == "启动跟单"

def test_add_account_dialog_opens(main_window, qtbot, mocker):
    """测试"添加账户"按钮是否能正确打开账户配置对话框。"""
    # 模拟对话框的 exec_ 方法，防止其在测试中阻塞
    mock_exec = mocker.patch('gui.main_window.AccountConfigDialog.exec_', return_value=1)
    
    # 模拟点击"添加账户"按钮
    qtbot.mouseClick(main_window.add_account_btn, Qt.LeftButton)
    
    # 断言对话框的 exec_ 方法被调用了一次
    mock_exec.assert_called_once()

def test_position_table_update(main_window, qtbot):
    """测试当后台工作线程发出 position_updated 信号时，持仓表格是否正确更新。"""
    # 初始状态：表格应为空
    assert main_window.position_table_model.rowCount() == 0

    # 模拟后台线程发送的持仓数据
    positions_data = [{
        "master_ticket": 123,
        "master_symbol": "EURUSD",  # 添加主账户品种
        "follower_positions": {
            "Follower1": {"ticket": 456, "volume": 0.1, "profit": 10.5, "type": "BUY"}
        }
    }]
    
    # 直接调用与信号连接的槽函数，来模拟信号发射
    main_window._update_positions(positions_data)

    # 断言表格现在应有一行数据
    assert main_window.position_table_model.rowCount() == 1
    
    # 断言第一行数据是否正确
    model = main_window.position_table_model
    
    # 检查主账户品种（第一列）
    index = model.index(0, 0)
    assert model.data(index, Qt.DisplayRole) == "EURUSD"
    
    # 检查主单号（第二列）
    index = model.index(0, 1)
    assert model.data(index, Qt.DisplayRole) == "123"  # 注意：model返回的是字符串

def test_account_status_update(main_window, qtbot):
    """测试账户状态更新功能。"""
    # 记录更新前的行数
    initial_row_count = main_window.account_table_model.rowCount()
    
    # 模拟账户状态数据
    account_statuses = [
        {
            "name": "测试账户1",
            "enabled": True,
            "connection_status": "已连接",
            "balance": 10000.0,
            "equity": 10050.0,
            "margin": 100.0
        },
        {
            "name": "测试账户2",
            "enabled": False,
            "connection_status": "未连接",
            "balance": 5000.0,
            "equity": 4950.0,
            "margin": 50.0
        }
    ]
    
    # 调用更新方法
    main_window._update_account_status(account_statuses)
    
    # 断言表格的数据已更新
    assert main_window.account_table_model.rowCount() >= initial_row_count
    
    # 检查数据是否已经添加或更新
    model = main_window.account_table_model
    test_acc1_found = False
    test_acc2_found = False
    
    # 打印当前表格中所有账户名称，以便于调试
    account_names = [model.data(model.index(row, 1), Qt.DisplayRole) for row in range(model.rowCount())]
    print(f"当前表格中的账户名称: {account_names}")
    
    # 遍历所有行，检查是否包含我们的测试数据
    for row in range(model.rowCount()):
        name_index = model.index(row, 1)  # 账户名在第2列（索引1）
        name = model.data(name_index, Qt.DisplayRole)
        
        if name == "测试账户1":
            test_acc1_found = True
            # 检查余额（第4列，索引3）
            balance_index = model.index(row, 3)
            balance_str = model.data(balance_index, Qt.DisplayRole)
            # 模型返回的可能是格式化的字符串，如"10000.00"
            assert "10000" in str(balance_str), f"测试账户1余额不匹配：{balance_str}"
            
        elif name == "测试账户2":
            test_acc2_found = True
    # 检查余额
            balance_index = model.index(row, 3)
            balance_str = model.data(balance_index, Qt.DisplayRole)
            assert "5000" in str(balance_str), f"测试账户2余额不匹配：{balance_str}"
    
    # 确保我们至少找到了一个测试账户
    assert test_acc1_found or test_acc2_found, "未能在模型中找到测试账户数据"

def test_connection_status_update(main_window, qtbot):
    """测试连接状态更新功能。"""
    # 找到一个现有账户或添加测试账户
    account_name = "TestAccount"
    account_exists = False
    
    # 检查是否已经有账户
    model = main_window.account_table_model
    for row in range(model.rowCount()):
        name_index = model.index(row, 1)  # 账户名在第2列（索引1）
        if model.data(name_index, Qt.DisplayRole) == account_name:
            account_exists = True
            break
    
    # 如果不存在，添加一个测试账户
    if not account_exists:
    main_window._update_account_status([{
            "name": account_name,
        "enabled": True,
        "connection_status": "未连接",
        "balance": 10000.0
    }])
    
    # 更新连接状态
    main_window._update_connection_status(account_name, "已连接")
    
    # 打印调试信息
    account_names = [model.data(model.index(row, 1), Qt.DisplayRole) for row in range(model.rowCount())]
    print(f"当前表格中的账户名称: {account_names}")
    
    # 断言状态已更新
    status_updated = False
    for row in range(model.rowCount()):
        name_index = model.index(row, 1)  # 账户名在第2列（索引1）
        if model.data(name_index, Qt.DisplayRole) == account_name:
            status_index = model.index(row, 2)  # 连接状态列在第3列(索引2)
            status_value = str(model.data(status_index, Qt.DisplayRole))
            print(f"找到账户 {account_name}，状态为 '{status_value}'")
            if "已连接" in status_value:
                status_updated = True
            break
    
    assert status_updated, f"账户 {account_name} 的连接状态未能更新为'已连接'"

def test_log_append(main_window, qtbot):
    """测试日志追加功能。"""
    # 先清空日志区域
    main_window.log_text.clear()
    assert main_window.log_text.toPlainText() == ""
    
    # 追加日志
    test_message = "这是一条测试日志"
    main_window._append_log(test_message)
    
    # 断言日志已追加
    assert test_message in main_window.log_text.toPlainText()
    
    # 追加另一条日志
    second_message = "这是第二条测试日志"
    main_window._append_log(second_message)
    
    # 断言两条日志都存在
    log_text = main_window.log_text.toPlainText()
    assert test_message in log_text
    assert second_message in log_text

def test_clear_logs(main_window, qtbot):
    """测试清除日志功能。"""
    # 首先确保日志不为空
    main_window.log_text.clear()
    main_window._append_log("测试日志1")
    main_window._append_log("测试日志2")
    
    # 确认日志不为空
    assert "测试日志1" in main_window.log_text.toPlainText()
    assert "测试日志2" in main_window.log_text.toPlainText()
    
    # 清除日志
    main_window._clear_logs()
    
    # 由于_clear_logs会添加一条"日志已清空"的消息，我们检查之前的测试日志已被移除
    assert "测试日志1" not in main_window.log_text.toPlainText()
    assert "测试日志2" not in main_window.log_text.toPlainText()
    assert "日志已清空" in main_window.log_text.toPlainText()

def test_complex_position_update(main_window, qtbot):
    """测试复杂的持仓更新场景。"""
    # 模拟一个复杂的持仓数据结构
    positions_data = [
        {
            "master_symbol": "EURUSD",
            "master_ticket": 123,
            "master_volume": 0.3,
            "master_profit": 20.5,
            "master_type": "BUY",
            "follower_positions": {
                "Follower1": {"ticket": 456, "volume": 0.1, "profit": 10.5, "type": "BUY"},
                "Follower2": {"ticket": 789, "volume": 0.2, "profit": -5.3, "type": "BUY"}
            }
        },
        {
            "master_symbol": "GBPUSD",
            "master_ticket": 456,
            "master_volume": 0.5,
            "master_profit": -10.2,
            "master_type": "SELL",
            "follower_positions": {
                "Follower1": {"ticket": 101112, "volume": 0.3, "profit": 15.7, "type": "SELL"}
            }
        }
    ]
    
    # 先确保有账户状态存在
    main_window._update_account_status([
        {"name": "Follower1", "enabled": True},
        {"name": "Follower2", "enabled": True}
    ])
    
    # 然后设置跟单账户列（这步很重要）
    main_window.position_table_model.set_follower_accounts(["Follower1", "Follower2"])
    
    # 更新持仓表格
    main_window._update_positions(positions_data)
    
    # 断言表格有两行数据
    assert main_window.position_table_model.rowCount() == 2
    
    # 检查第一行的数据
    model = main_window.position_table_model
    
    # 检查第一行主账户品种
    index = model.index(0, 0)
    assert model.data(index, Qt.DisplayRole) == "EURUSD"
    
    # 检查第一行主账户单号
    index = model.index(0, 1)
    assert model.data(index, Qt.DisplayRole) == "123"
    
    # 检查第二行的数据
    index = model.index(1, 0)  # 第二行品种
    assert model.data(index, Qt.DisplayRole) == "GBPUSD"
    
    index = model.index(1, 1)  # 第二行主单号
    assert model.data(index, Qt.DisplayRole) == "456" 