from PyQt5.QtCore import QObject, pyqtSignal, QThread
import logging
from core.config_manager import ConfigManager
from core.account_manager import AccountManager
from core.trade_engine import TradeEngine
from core.zmq_listener import ZmqListener
from core.connection_manager import ConnectionManager


class CoreWorker(QObject):
    """Background worker running trading components in a separate thread."""

    log_received = pyqtSignal(str)
    status_updated = pyqtSignal(str, str)

    def __init__(self, config_path: str = "config/config.json") -> None:
        super().__init__()
        self.config_manager = ConfigManager(config_path)
        self.connection_manager = ConnectionManager(self.config_manager)
        self.account_manager = AccountManager(self.config_manager)
        self.trade_engine = TradeEngine(self.config_manager, self.account_manager)
        self.zmq_listener = ZmqListener(
            config_manager=self.config_manager,
            event_callback=self.trade_engine.process_event,
            state_sync_callback=self.trade_engine.sync_state,
        )
        self.thread: QThread | None = None
        self.running = False
        self.logger = logging.getLogger("TradeCopier.GUIWorker")

    # ------------------------------------------------------------------
    # Public slots
    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        # Connect accounts and start monitoring
        for acc in self.config_manager.get_follower_accounts():
            self.connection_manager.connect_account(acc["name"])
        self.connection_manager.start_monitoring()
        self.zmq_listener.start()
        self.log_received.emit("Trading started")

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.zmq_listener.stop()
        self.account_manager.shutdown()
        self.connection_manager.stop_monitoring()
        self.log_received.emit("Trading stopped")

    # ------------------------------------------------------------------
    # Helpers invoked by trading components
    # ------------------------------------------------------------------
    def handle_log(self, record: dict) -> None:
        self.log_received.emit(str(record))

