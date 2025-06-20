import pytest
from unittest.mock import patch, MagicMock
from PyQt5.QtCore import Qt

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
    assert main_window.log_text_edit is not None

def test_start_stop_buttons(main_window, qtbot):
    """Test the functionality of the start and stop buttons."""
    # The worker's methods are mocked, so we test if they are called
    main_window._start_trading = MagicMock()
    main_window._stop_trading = MagicMock()

    # Click start button
    qtbot.mouseClick(main_window.start_button, Qt.LeftButton)
    main_window._start_trading.assert_called_once()

    # Click stop button
    qtbot.mouseClick(main_window.stop_button, Qt.LeftButton)
    main_window._stop_trading.assert_called_once()

def test_add_account_dialog_opens(main_window, qtbot, mocker):
    """测试"添加账户"按钮是否能正确打开账户配置对话框。"""
    # 模拟对话框的 exec_ 方法，防止其在测试中阻塞
    mock_exec = mocker.patch('python.gui.account_dialog.AccountConfigDialog.exec_', return_value=1)
    
    # 模拟点击"添加账户"按钮
    qtbot.mouseClick(main_window.add_account_btn, Qt.LeftButton)
    
    # 断言对话框的 exec_ 方法被调用了一次
    mock_exec.assert_called_once()

def test_position_table_update(main_window, qtbot):
    """测试当后台工作线程发出 position_updated 信号时，持仓表格是否正确更新。"""
    # 初始状态：表格应为空
    assert main_window.position_model.rowCount() == 0

    # 模拟后台线程发送的持仓数据
    positions_data = [{
        "master_symbol": "EURUSD", "master_ticket": 123, "master_volume": 0.1,
        "master_profit": 10.5, "master_type": "BUY",
        "follower_positions": {
            "Follower1": {"ticket": 456, "volume": 0.1, "profit": 10.5, "type": "BUY"}
        }
    }]
    
    # 直接调用与信号连接的槽函数，来模拟信号发射
    main_window._update_positions(positions_data)

    # 断言表格现在应有一行数据
    assert main_window.position_model.rowCount() == 1
    
    # 断言第一行第一列（品种）的数据是否正确
    model = main_window.position_model
    index = model.index(0, 0) # 第 0 行, 第 0 列
    assert model.data(index, Qt.DisplayRole) == "EURUSD" 