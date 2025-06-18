"""Connection manager for MT5 terminals.

This module manages connections to multiple MetaTrader5 terminals.
It can auto-discover running terminals, connect to them after the user
starts the terminal manually, and monitor the connection state.
"""

import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import MetaTrader5 as mt5


class ConnectionStatus(Enum):
    """Status of the connection to an MT5 terminal."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    RECONNECTING = "reconnecting"


@dataclass
class AccountConnection:
    """State for a follower account connection."""

    name: str
    login: int
    server: str
    status: ConnectionStatus
    last_ping: float
    error_count: int
    connection_time: Optional[float] = None


class ConnectionManager:
    """Manage persistent MT5 connections for follower accounts."""

    def __init__(self, config_manager) -> None:
        self.config_manager = config_manager
        self.connections: Dict[str, AccountConnection] = {}
        self.monitor_thread: Optional[threading.Thread] = None
        self.running = False
        self.ping_interval = 30  # seconds

    # ------------------------------------------------------------------
    # Discovery and connect
    # ------------------------------------------------------------------
    def auto_discover_accounts(self) -> List[Dict[str, int]]:
        """Discover running MT5 terminals.

        Returns a list of dictionaries describing detected accounts.
        """
        discovered: List[Dict[str, int]] = []
        common_paths = [
            r"C:\\Program Files\\MetaTrader 5\\terminal64.exe",
            r"C:\\Program Files (x86)\\MetaTrader 5\\terminal64.exe",
            r"D:\\metatrader5\\v2-mt5\\terminal64.exe",
        ]

        for path in common_paths:
            if self._check_mt5_instance(path):
                info = self._get_account_info(path)
                if info:
                    discovered.append(
                        {
                            "path": path,
                            "login": info.login,
                            "server": info.server,
                            "balance": info.balance,
                        }
                    )
        return discovered

    def connect_account(self, account_name: str) -> bool:
        """Connect a follower account.

        The user is expected to have started the terminal manually.
        """
        config = self.config_manager.get_follower_config(account_name)
        if not config:
            return False

        connection = AccountConnection(
            name=account_name,
            login=config["login"],
            server=config["server"],
            status=ConnectionStatus.CONNECTING,
            last_ping=time.time(),
            error_count=0,
        )

        # Do not pass path so mt5 does not try to start the terminal
        # itself. We expect the user to start the terminal manually and
        # the API will attach to the running instance.
        if mt5.initialize(
            login=config["login"],
            password=config["password"],
            server=config["server"],
        ):
            connection.status = ConnectionStatus.CONNECTED
            connection.connection_time = time.time()
            self.connections[account_name] = connection
            return True

        connection.status = ConnectionStatus.ERROR
        connection.error_count += 1
        return False

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------
    def start_monitoring(self) -> None:
        """Start background monitoring of all connections."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.running = True
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop, name="ConnectionMonitor", daemon=True
        )
        self.monitor_thread.start()

    def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join()

    def _monitor_loop(self) -> None:
        while self.running:
            for account_name, connection in list(self.connections.items()):
                if connection.status == ConnectionStatus.CONNECTED:
                    if not self._ping_account(account_name):
                        self._handle_connection_lost(account_name)
                elif connection.status == ConnectionStatus.ERROR:
                    if connection.error_count < 5:
                        self._attempt_reconnection(account_name)
            time.sleep(self.ping_interval)

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------
    def get_connection_status(self) -> Dict[str, Dict[str, float]]:
        """Return status for all connections."""
        status_dict: Dict[str, Dict[str, float]] = {}
        for name, conn in self.connections.items():
            status_dict[name] = {
                "status": conn.status.value,
                "last_ping": conn.last_ping,
                "error_count": conn.error_count,
                "uptime": time.time() - conn.connection_time
                if conn.connection_time
                else 0,
            }
        return status_dict

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ping_account(self, account_name: str) -> bool:
        try:
            info = mt5.account_info()
            if info is not None:
                self.connections[account_name].last_ping = time.time()
                return True
        except Exception:
            pass
        return False

    def _handle_connection_lost(self, account_name: str) -> None:
        connection = self.connections.get(account_name)
        if connection:
            connection.status = ConnectionStatus.ERROR
            connection.error_count += 1
            mt5.shutdown()

    def _attempt_reconnection(self, account_name: str) -> None:
        connection = self.connections.get(account_name)
        if not connection:
            return
        connection.status = ConnectionStatus.RECONNECTING
        cfg = self.config_manager.get_follower_config(account_name)
        if not cfg:
            return
        if mt5.initialize(
            path=cfg.get("mt5_path"),
            login=cfg["login"],
            password=cfg["password"],
            server=cfg["server"],
        ):
            connection.status = ConnectionStatus.CONNECTED
            connection.error_count = 0
            if connection.connection_time is None:
                connection.connection_time = time.time()
        else:
            connection.error_count += 1
            connection.status = ConnectionStatus.ERROR

    def _check_mt5_instance(self, path: str) -> bool:
        return os.path.exists(path)

    def _get_account_info(self, path: str):
        if not mt5.initialize(path=path):
            return None
        info = mt5.account_info()
        mt5.shutdown()
        return info
