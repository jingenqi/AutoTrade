import zmq
import time
import json
import sys
import os

# 将项目根目录添加到路径中以导入设置
# 假设脚本在 `python` 目录中运行
sys.path.insert(0, os.path.abspath('.'))
from config import settings


def main():
    # 运行 ZMQ 测试客户端的主函数。
    context = zmq.Context()

    print("--- MT5 ZMQ Python 测试客户端 ---")
    settings.print_zmq_config()

    # --- 步骤 1: 执行 REQ/REP 握手以进行同步 ---
    print(f"正在连接到 {settings.ZMQ_SYNC_URI} 上的 REP 套接字进行握手...")
    req_socket = context.socket(zmq.REQ)
    req_socket.connect(settings.ZMQ_SYNC_URI)

    print("正在发送 'SYNC' 消息...")
    req_socket.send_string(settings.MSG_SYNC_REQUEST)

    # 等待 "ACK" 回复，带超时
    poller = zmq.Poller()
    poller.register(req_socket, zmq.POLLIN)

    ack_received = False
    socks = dict(poller.poll(5000))  # 5 秒超时
    if req_socket in socks and socks[req_socket] == zmq.POLLIN:
        message = req_socket.recv_string()
        if message == settings.MSG_SYNC_RESPONSE:
            print("收到 'ACK'。握手成功！")
            ack_received = True
        else:
            print(f"错误: 收到意外消息: {message}")
    else:
        print("错误: 握手超时。未从 EA 收到 'ACK'。")
        print("请确保 TradeCopierMaster EA 正在 MT5 的图表上运行。")

    req_socket.close()

    if not ack_received:
        context.term()
        return

    # --- 步骤 2: 订阅 PUB 套接字以获取交易事件 ---
    print(f"\n正在连接到 {settings.ZMQ_BUS_URI} 上的 PUB 套接字...")
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(settings.ZMQ_BUS_URI)
    sub_socket.setsockopt_string(zmq.SUBSCRIBE, "TRADE_EVENT")

    print(f"已订阅主题: 'TRADE_EVENT'")
    print("正在等待交易事件... (在 MT5 中执行交易以查看消息)")
    print("按 Ctrl+C 退出。")

    try:
        while True:
            # 读取多部分消息
            topic, payload_raw = sub_socket.recv_multipart()

            print("\n--- 收到事件 ---")
            print(f"主题: {topic.decode()}")
            try:
                # 负载作为 JSON 字符串发送
                payload = json.loads(payload_raw.decode('utf-8'))
                # 美化打印 JSON
                print("负载:")
                print(json.dumps(payload, indent=2))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"解码负载错误: {e}")
                print(f"原始负载: {payload_raw}")
            print("----------------------")

    except KeyboardInterrupt:
        print("\n正在退出...")
    finally:
        sub_socket.close()
        context.term()
        print("ZMQ 上下文已终止。")


if __name__ == "__main__":
    main() 