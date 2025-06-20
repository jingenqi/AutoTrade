#!/usr/bin/env python3
import os
import platform

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
# 默认值是 "tcp"，确保生产环境的最高性能。
TRANSPORT = os.environ.get("ZMQ_TRANSPORT", "tcp").lower()


# --- 2. 网络配置 (仅当 TRANSPORT = "tcp" 时生效) ---
# 您可以通过设置环境变量 ZMQ_TCP_HOST 来覆盖此处的 IP 地址。
# 默认值是 "localhost" (本机)。
TCP_HOST = os.environ.get("ZMQ_TCP_HOST", "localhost")
SYNC_PORT = 5555  # REQ/REP 同步端口
BUS_PORT = 5556   # PUB/SUB 事件总线端口


# --- 3. IPC 配置 (仅当 TRANSPORT = "ipc" 时生效) ---
# 这些是将在项目根目录下创建的 IPC 套接字文件名。
# MQL5 EA 和 Python 脚本都需要访问这些文件，请确保路径对于双方都是正确的。
IPC_SYNC_PATH = "mt5_sync.ipc"
IPC_BUS_PATH = "mt5_trade.ipc"


# --- 4. 动态生成 ZMQ 连接地址 ---
# 下面的代码会根据您在上面选择的 TRANSPORT 模式，自动构建正确的连接字符串。
if TRANSPORT == "ipc":
    if platform.system() == "Windows":
        # 在 Windows 上，IPC 通过命名管道实现。
        # 格式为 ipc://\\.\pipe\pipename
        ZMQ_SYNC_URI = f"ipc://\\\\.\\pipe\\{IPC_SYNC_PATH}"
        ZMQ_BUS_URI = f"ipc://\\\\.\\pipe\\{IPC_BUS_PATH}"
    else:
        # 在 Linux/macOS 上，IPC 使用文件系统套接字。
        # 注意：您可能需要管理文件权限和清理。
        ZMQ_SYNC_URI = f"ipc://{IPC_SYNC_PATH}"
        ZMQ_BUS_URI = f"ipc://{IPC_BUS_PATH}"
else:  # 默认为 TCP
    ZMQ_SYNC_URI = f"tcp://{TCP_HOST}:{SYNC_PORT}"
    ZMQ_BUS_URI = f"tcp://{TCP_HOST}:{BUS_PORT}"
    

def print_zmq_config():
    # 打印当前的 ZMQ 配置到控制台。
    print("--- ZMQ 配置 ---")
    print(f"模式:      {TRANSPORT.upper()}")
    if TRANSPORT == 'tcp':
        print(f"主机:      {TCP_HOST} (由 ZMQ_TCP_HOST 环境变量设置)")
    print(f"同步 URI:  {ZMQ_SYNC_URI}")
    print(f"总线 URI:   {ZMQ_BUS_URI}")
    print("-------------------")


# --- 5. 共享消息常量 ---
MSG_SYNC_REQUEST = "SYNC"
MSG_SYNC_RESPONSE = "ACK"
MSG_HEARTBEAT = "HEARTBEAT" 