import zmq
import threading
from typing import Callable, Optional, Dict, Any
import logging
import time
import json

from config import settings
from core.config_manager import ConfigManager
from core.events import create_event_from_dict, HeartbeatEvent

# 设置日志
logger = logging.getLogger("TradeCopier.ZmqListener")

class ZmqListener:
    # 负责监听来自 MT5 EA 的 ZeroMQ 消息（包括同步和交易事件）。在单独的线程中运行，以避免阻塞主应用程序。
    def __init__(
        self,
        config_manager: ConfigManager,
        event_callback: Callable[[Dict[str, Any]], None], # 接受解析后的事件字典
        state_sync_callback: Callable[[Dict[str, Any]], None]
    ):
        # 初始化 ZmqListener。
        # Args:
        #     config_manager: ConfigManager 的实例。
        #     event_callback: 用于处理接收到的交易事件的回调函数。
        #     state_sync_callback: 用于处理 EA 状态同步的回调函数。
        self.config_manager = config_manager
        self.event_callback = event_callback
        self.state_sync_callback = state_sync_callback
        self.context = None
        self.sync_socket = None
        self.bus_socket = None
        self.running = False
        self.listener_thread = None

        # ZMQ 设置
        zmq_settings = self.config_manager.get_zmq_settings()
        self.transport = zmq_settings.get("transport", "tcp")
        self.tcp_host = zmq_settings.get("tcp_host", "localhost")
        self.sync_port = zmq_settings.get("sync_port", 5555)
        self.bus_port = zmq_settings.get("bus_port", 5556)

        # 根据传输模式构建 URI
        if self.transport == "ipc":
            self.sync_uri = f"ipc://{zmq_settings.get('ipc_sync_path', 'mt5_sync.ipc')}"
            self.bus_uri = f"ipc://{zmq_settings.get('ipc_bus_path', 'mt5_trade.ipc')}"
        else: # 默认为 tcp
            self.sync_uri = f"tcp://{self.tcp_host}:{self.sync_port}"
            self.bus_uri = f"tcp://{self.tcp_host}:{self.bus_port}"

        # 心跳配置
        self.heartbeat_interval = 5  # 秒
        self.last_heartbeat_time = time.time()

        logger.debug("ZmqListener 已初始化。")

    def start(self):
        # 启动监听器的主控制循环。
        if self.running:
            logger.warning("ZMQ 监听器已在运行。")
            return
        self.running = True
        self.listener_thread = threading.Thread(target=self._listen_loop, name="ZmqListenerThread")
        self.listener_thread.daemon = True # 允许程序在线程仍在运行时退出
        self.listener_thread.start()
        logger.debug("ZmqListener 线程已启动。")

    def stop(self):
        # 停止监听器线程并等待其终止。
        if not self.running:
            logger.warning("ZMQ 监听器未在运行。")
            return
        logger.info("正在停止 ZMQ 监听器...")
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=5) # 等待线程终止
            if self.listener_thread.is_alive():
                logger.warning("ZMQ 监听器线程未能及时终止。")
        self._close_sockets()
        logger.info("ZMQ 监听器已停止。")

    def _close_sockets(self):
        # 关闭所有 ZeroMQ 套接字并终止上下文。
        if self.bus_socket:
            self.bus_socket.close()
            self.bus_socket = None
            logger.debug("总线套接字已关闭。")
        if self.sync_socket:
            self.sync_socket.close()
            self.sync_socket = None
            logger.debug("同步套接字已关闭。")
        if self.context:
            self.context.term()
            self.context = None
            logger.debug("ZMQ 上下文已终止。")

    def _listen_loop(self):
        # 监听器线程的主控制循环。这个循环管理连接状态并在连接丢失时尝试重新连接。
        logger.info("ZMQ 监听器控制线程已启动。")
        # 初始化轮询器
        self.poller = zmq.Poller()
        while self.running:
            try:
                if not self._ensure_connection():
                    logger.warning("无法建立与 EA 的连接。在重试前等待。")
                    time.sleep(self.config_manager.get_setting("reconnect_delay", 5)) # 可配置的重连延迟
                    continue

                self._perform_stateful_handshake()
                logger.info(f"连接已建立。正在监听来自 {self.bus_uri} 的事件...")
                self._receive_events()

            except zmq.Again as e:
                # 非阻塞操作，没有收到消息
                # logger.debug("ZMQ 非阻塞操作: 未收到消息。") # 过于频繁，改为警告
                time.sleep(0.1) # 短暂睡眠以避免 CPU 占用过高
            except zmq.ZMQError as e:
                logger.error(f"ZMQ 错误: {e}", exc_info=True)
                self._close_sockets() # 强制关闭套接字以进行干净的重新连接
                time.sleep(self.config_manager.get_setting("reconnect_delay", 5))
            except Exception as e:
                logger.error(f"监听循环中发生意外错误: {e}", exc_info=True)
                self._close_sockets() # 确保在所有错误上关闭套接字
                time.sleep(self.config_manager.get_setting("reconnect_delay", 5))

    def _ensure_connection(self) -> bool:
        # 确保 ZeroMQ 套接字已初始化并连接。
        # Returns:
        #     bool: 如果连接成功则为 True，否则为 False。
        if self.context and self.sync_socket and self.bus_socket:
            return True # 已经连接

        self._close_sockets() # 确保从干净状态开始

        try:
            self.context = zmq.Context()
            
            # 同步套接字 (REQ/REP)
            self.sync_socket = self.context.socket(zmq.REQ)
            self.sync_socket.setsockopt(zmq.RCVTIMEO, 5000) # 5 秒接收超时
            self.sync_socket.setsockopt(zmq.REQ_CORRELATE, 1)
            self.sync_socket.setsockopt(zmq.REQ_RELAXED, 1)
            logger.debug(f"连接到同步 URI: {self.sync_uri}")
            self.sync_socket.connect(self.sync_uri)
            self.poller.register(self.sync_socket, zmq.POLLIN) # 注册同步套接字到轮询器

            # 事件总线套接字 (SUB)
            self.bus_socket = self.context.socket(zmq.SUB)
            self.bus_socket.setsockopt_string(zmq.SUBSCRIBE, "TRADE_EVENT") # 订阅所有交易事件
            self.bus_socket.setsockopt_string(zmq.SUBSCRIBE, "HEARTBEAT") # 订阅心跳
            self.bus_socket.setsockopt(zmq.RCVTIMEO, 1000) # 1 秒接收超时用于心跳检测
            logger.debug(f"连接到总线 URI: {self.bus_uri}")
            self.bus_socket.connect(self.bus_uri)
            self.poller.register(self.bus_socket, zmq.POLLIN) # 注册总线套接字到轮询器
            
            logger.info("ZMQ 套接字已成功创建并连接。")
            return True
        except zmq.ZMQError as e:
            logger.error(f"ZMQ 连接错误: {e}. URI: {self.sync_uri} 或 {self.bus_uri}")
            self._close_sockets()
            return False
        except Exception as e:
            logger.error(f"创建 ZMQ 连接时发生意外错误: {e}", exc_info=True)
            self._close_sockets()
            return False

    def _perform_stateful_handshake(self):
        # 执行与 MQL5 EA 的状态感知同步，通过请求所有持仓和订单的当前状态。
        # 这个函数假定 self.sync_socket 已经连接。
        logger.info(f"正在与 EA 在 {self.sync_uri} 上执行状态握手...")
        try:
            # 1. 发送 SYNC 请求
            self.sync_socket.send_string("SYNC")
            logger.debug("已发送 SYNC 请求。")

            # 2. 接收 ACK 响应
            response = self.sync_socket.recv_string()
            if response == "ACK":
                logger.debug("接收到 ACK。同步成功。")
            else:
                logger.warning(f"同步失败：接收到意外响应 '{response}'。")
                # 如果同步失败，尝试重新连接
                self._close_sockets()
                return
            
            # 3. 发送 GET_STATE 请求
            self.sync_socket.send_string("GET_STATE")
            logger.debug("已发送 GET_STATE 请求。")

            # 4. 接收状态 JSON
            state_json = self.sync_socket.recv_string()
            logger.debug(f"接收到状态 JSON: {state_json[:200]}...") # 限制日志长度
            
            # 解析并传递状态给回调
            state_data = json.loads(state_json)
            self.state_sync_callback(state_data)
            logger.info("状态同步与 EA 成功。")

        except zmq.Again:
            logger.warning("接收超时（EA 未响应握手）。连接可能已丢失。")
            self._close_sockets() # 强制关闭以触发重连
        except json.JSONDecodeError as e:
            logger.error(f"解析 EA 状态 JSON 失败: {e}. JSON: {state_json}")
            self._close_sockets()
        except zmq.ZMQError as e:
            logger.error(f"握手期间发生 ZMQ 错误: {e}")
            self._close_sockets()
        except Exception as e:
            logger.error(f"握手期间发生意外错误: {e}", exc_info=True)
            self._close_sockets()

    def _receive_events(self):
        # 监听 SUB 套接字上的交易事件。如果EA在特定时间段内未收到消息，则此循环将退出，假设与EA的连接已丢失。
        while self.running:
            try:
                # 轮询总线套接字，检查是否有消息或心跳超时
                if not self.bus_socket: # 如果套接字在其他地方被关闭
                    break

                # 使用 poll 检查消息，带有心跳超时
                socks = dict(self.poller.poll(self.heartbeat_interval * 1000))

                if self.bus_socket in socks and socks[self.bus_socket] == zmq.POLLIN:
                    # 接收多部分消息：主题和数据
                    topic = self.bus_socket.recv_string(zmq.DONTWAIT)
                    payload = self.bus_socket.recv_string(zmq.DONTWAIT)
                    
                    if topic == "HEARTBEAT":
                        # 处理心跳
                        self.last_heartbeat_time = time.time()
                        logger.debug("收到心跳。")
                        # 可以选择触发一个心跳事件到主引擎
                        self.event_callback(HeartbeatEvent(timestamp=int(time.time() * 1000)).__dict__)
                    elif topic == "TRADE_EVENT":
                        # 处理交易事件
                        try:
                            event_dict = json.loads(payload)
                            # logger.debug(f"接收到原始事件: {payload}") # 调试时启用
                            self.event_callback(event_dict)
                        except json.JSONDecodeError as e:
                            logger.error(f"解码事件 JSON 失败: {e}. Payload: {payload}")
                        except Exception as e:
                            logger.error(f"处理接收到的事件时发生错误: {e}. Payload: {payload}", exc_info=True)
                    else:
                        logger.warning(f"接收到未知主题 '{topic}' 的消息。")

                # 如果超过心跳间隔没有收到心跳，则认为连接丢失
                # if time.time() - self.last_heartbeat_time > (self.heartbeat_interval * 2):
                #    logger.warning("Receive timeout (no heartbeat from EA). Connection may be lost.")
                #    self._close_sockets() # 强制关闭以触发重连

            except zmq.Again:
                # 非阻塞操作，没有收到消息，这通常不是错误，只是没有事件发生
                # logger.debug("ZMQ 非阻塞操作: 未收到消息。")
                pass
            except zmq.ZMQError as e:
                logger.error(f"ZMQ 事件接收错误: {e}", exc_info=True)
                self._close_sockets() # 强制关闭套接字以进行干净的重新连接
                break # 退出循环以尝试重新连接
            except Exception as e:
                logger.error(f"接收事件时发生意外错误: {e}", exc_info=True)
                self._close_sockets() # 确保在所有错误上关闭套接字
                break # 退出循环以尝试重新连接

    def _listen_for_events(self):
        # 持续监听 ZeroMQ 事件总线以获取事件。此函数在当前实现中可能未被直接使用，其逻辑已合并到 _receive_events。保留此函数是为了可能的未来扩展或作为参考。
        pass # 逻辑已合并到 _receive_events

    def stop(self):
        # 停止监听器线程并等待其终止。
        if not self.running:
            logger.warning("ZMQ 监听器未在运行。")
            return
        logger.info("正在停止 ZMQ 监听器...")
        self.running = False
        if self.listener_thread:
            self.listener_thread.join(timeout=5) # 等待线程终止
            if self.listener_thread.is_alive():
                logger.warning("ZMQ 监听器线程未能及时终止。")
        self._close_sockets()
        logger.info("ZMQ 监听器已停止。") 