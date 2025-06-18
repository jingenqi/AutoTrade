from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QMessageBox,
)
from PyQt5.QtCore import Qt, QThread

from .worker import CoreWorker


class MainWindow(QMainWindow):
    """Simple GUI for managing the trade copier."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MT5 Trade Copier")
        self.resize(800, 600)
        self.worker = CoreWorker()

        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.start()

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)

        self.account_table = QTableWidget()
        accounts = self.worker.config_manager.get_follower_accounts()
        self.account_table.setColumnCount(2)
        self.account_table.setHorizontalHeaderLabels(["Account", "Enabled"])
        self.account_table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            self.account_table.setItem(row, 0, QTableWidgetItem(acc["name"]))
            enabled_item = QTableWidgetItem("Yes" if acc.get("enabled") else "No")
            enabled_item.setTextAlignment(Qt.AlignCenter)
            self.account_table.setItem(row, 1, enabled_item)
        self.account_table.resizeColumnsToContents()
        layout.addWidget(self.account_table)

        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        self.setCentralWidget(central)

    def _connect_signals(self):
        self.start_btn.clicked.connect(self.worker.start)
        self.stop_btn.clicked.connect(self.worker.stop)
        self.worker.log_received.connect(self._append_log)

    def _append_log(self, message: str):
        self.log_box.appendPlainText(message)

    def closeEvent(self, event):
        self.worker.stop()
        self.thread.quit()
        self.thread.wait()
        event.accept()


def run_gui():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec_()


if __name__ == "__main__":
    run_gui()
