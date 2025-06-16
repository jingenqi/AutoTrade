#!/usr/bin/env python3
import os

"""
全局配置文件
----------------------------------------------------------------
通过此文件可以轻松切换应用的通信模式，以适应不同环境的需求。
"""

# --- 1. 通信模式选择 ---
# 在此设置全局通信协议。可用选项:
# - "ipc": 使用进程间通信。速度最快，延迟最低，适用于在同一台机器上运行的生产环境。
# - "tcp": 使用网络套接字。用于跨设备进行开发和测试。
# 
# 您可以通过设置环境变量 ZMQ_TRANSPORT 来覆盖此设置。
# 默认值是 "ipc"，确保生产环境的最高性能。
TRANSPORT = os.environ.get("ZMQ_TRANSPORT", "ipc").lower()


# --- 2. 网络配置 (仅当 TRANSPORT = "tcp" 时生效) ---
# 您可以通过设置环境变量 ZMQ_TCP_HOST 来覆盖此处的 IP 地址。
# 默认值是 "127.0.0.1" (本机)。
TCP_HOST = os.environ.get("ZMQ_TCP_HOST", "127.0.0.1")
SYNC_PORT = 5555  # REQ/REP 同步端口
BUS_PORT = 5556   # PUB/SUB 事件总线端口


# --- 3. IPC 配置 (仅当 TRANSPORT = "ipc" 时生效) ---
# 这些是将在项目根目录下创建的 IPC 套接字文件名。
# MQL5 EA 和 Python 脚本都需要访问这些文件，请确保路径对于双方都是正确的。
IPC_SYNC_FILE = "mt5_sync.ipc"
IPC_BUS_FILE = "mt5_trade_bus.ipc"


# --- 4. 动态生成 ZMQ 连接地址 ---
# 下面的代码会根据您在上面选择的 TRANSPORT 模式，自动构建正确的连接字符串。
print("--- ZMQ Configuration ---")
if TRANSPORT == "tcp":
    ZMQ_SYNC_URI = f"tcp://{TCP_HOST}:{SYNC_PORT}"
    ZMQ_BUS_URI = f"tcp://{TCP_HOST}:{BUS_PORT}"
    print(f"Mode:      TCP")
    print(f"Host:      {TCP_HOST} (set by ZMQ_TCP_HOST env var)")
    print(f"Sync URI:  {ZMQ_SYNC_URI}")
    print(f"Bus URI:   {ZMQ_BUS_URI}")
else:
    ZMQ_SYNC_URI = f"ipc://{IPC_SYNC_FILE}"
    ZMQ_BUS_URI = f"ipc://{IPC_BUS_FILE}"
    print(f"Mode:      IPC (default)")
    print(f"Sync URI:  {ZMQ_SYNC_URI}")
    print(f"Bus URI:   {ZMQ_BUS_URI}")
print("-------------------------")


# --- 5. 共享消息常量 ---
MSG_SYNC_REQUEST = "READY?"
MSG_SYNC_RESPONSE = "ACK"
MSG_HEARTBEAT = "HEARTBEAT" 