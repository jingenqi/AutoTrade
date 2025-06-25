import zmq
import threading
from typing import Callable, Dict, Any
import logging
import time
import json

from .config_manager import ConfigManager
from .error_handler import handle_exceptions, with_retry, ErrorCategory, HandledException
from .events import create_event_from_dict, HeartbeatEvent

logger = logging.getLogger("TradeCopier.ZmqListener")

class ZmqListener:
    # 负责监听来自 MT5 EA 的 ZeroMQ 消息
    def __init__(self, config_manager: ConfigManager, event_callback: Callable[[Dict[str, Any]], None], state_sync_callback: Callable[[Dict[str, Any]], None]):
        self.config_manager = config_manager
        self.event_callback = event_callback
        self.state_sync_callback = state_sync_callback
        self.context: zmq.Context = None
        self.sync_socket: zmq.Socket = None
        self.bus_socket: zmq.Socket = None
        self.poller: zmq.Poller = None
        self.running = False
        self.listener_thread = None
        self.last_heartbeat_time = time.time()
        self._setup_uris()
        
        # 心跳恢复机制
        self.heartbeat_timeout = 60.0  # 60秒无心跳视为断开
        self.heartbeat_warning_threshold = 30.0  # 30秒无心跳发出警告
        self.last_warning_time = 0  # 上次警告时间，避免频繁日志
        self.last_handshake_time = 0  # 上次握手成功时间
        
        # 重连机制
        self.reconnect_delay = 5  # 重连延迟（秒）
        self.max_reconnect_delay = 30  # 最大重连延迟
        self.current_reconnect_delay = self.reconnect_delay  # 当前重连延迟
        self.reconnect_attempts = 0  # 重连尝试次数

    # 根据配置构建 ZMQ 连接地址
    def _setup_uris(self):
        settings = self.config_manager.get_zmq_settings()
        transport = settings.get("transport", "tcp")
        if transport == "ipc":
            self.sync_uri = f"ipc://{settings.get('ipc_sync_path', 'mt5_sync.ipc')}"
            self.bus_uri = f"ipc://{settings.get('ipc_bus_path', 'mt5_trade.ipc')}"
        else:
            host = settings.get("tcp_host", "localhost")
            sync_port = settings.get("req_port", 5555)
            bus_port = settings.get("sub_port", 5556)
            self.sync_uri = f"tcp://{host}:{sync_port}"
            self.bus_uri = f"tcp://{host}:{bus_port}"

    # 启动监听器线程
    def start(self):
        if self.running:
            logger.warning("ZMQ 监听器已在运行。")
            return
        self.running = True
        self.listener_thread = threading.Thread(target=self._control_loop, name="ZmqListenerThread", daemon=True)
        self.listener_thread.start()
        logger.info("ZMQ 监听器已启动。")

    # 停止监听器线程
    def stop(self):
        if not self.running: return
        logger.info("正在停止 ZMQ 监听器...")
        self.running = False
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=2)
        self._close_sockets()
        logger.info("ZMQ 监听器已停止。")

    # 管理连接和接收的控制循环
    def _control_loop(self):
        while self.running:
            try:
                # 初始化套接字
                if not self._setup_sockets():
                    # 套接字初始化失败，使用退避算法延迟重试
                    self._handle_connection_failure()
                    continue
                
                # 执行握手和状态同步
                if not self._perform_handshake():
                    # 握手失败，使用退避算法延迟重试
                    self._handle_connection_failure()
                    continue
                    
                # 握手成功，重置重连参数
                self.reconnect_attempts = 0
                self.current_reconnect_delay = self.reconnect_delay
                
                # 开始接收事件循环
                self._receive_loop()
            except HandledException as e:
                if 'zmq.error.Again' in e.error_info.traceback_str:
                    logger.critical(f"连接EA失败: ZMQ超时")
                else:
                    logger.error(f"ZMQ 控制循环中发生已知错误: {e}", exc_info=False)
                self._handle_connection_failure()
            except Exception as e:
                logger.error(f"ZMQ 控制循环中发生意外错误，将在{self.current_reconnect_delay}秒后重试连接: {e}", exc_info=True)
                self._handle_connection_failure()

    # 处理连接失败的退避算法
    def _handle_connection_failure(self):
        self._close_sockets()
        self.reconnect_attempts += 1
        # 使用指数退避算法增加重试间隔，但不超过最大值
        self.current_reconnect_delay = min(
            self.reconnect_delay * (1.5 ** min(self.reconnect_attempts, 10)), 
            self.max_reconnect_delay
        )
        logger.warning(f"连接EA失败，第{self.reconnect_attempts}次尝试，将在{self.current_reconnect_delay:.1f}秒后重试")
        time.sleep(self.current_reconnect_delay)

    # 初始化或重新初始化 ZMQ 套接字
    def _setup_sockets(self):
        try:
            self._close_sockets()
            self.context = zmq.Context()
            self.poller = zmq.Poller()
            
            # 同步套接字 (REQ/REP)
            self.sync_socket = self.context.socket(zmq.REQ)
            self.sync_socket.setsockopt(zmq.RCVTIMEO, 5000) # 5秒超时
            self.sync_socket.setsockopt(zmq.LINGER, 0)  # 不延迟关闭
            self.sync_socket.connect(self.sync_uri)
            
            # 事件总线套接字 (SUB)
            self.bus_socket = self.context.socket(zmq.SUB)
            self.bus_socket.setsockopt_string(zmq.SUBSCRIBE, "")  # 订阅所有消息
            self.bus_socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1秒接收超时
            self.bus_socket.setsockopt(zmq.LINGER, 0)  # 不延迟关闭
            self.bus_socket.connect(self.bus_uri)
            
            # 只将需要被轮询的 SUB 套接字注册到 poller
            self.poller.register(self.bus_socket, zmq.POLLIN)
            logger.info(f"ZMQ 套接字已初始化。Sync: {self.sync_uri}, Bus: {self.bus_uri}")
            return True
        except zmq.ZMQError as e:
            logger.error(f"设置ZMQ套接字失败: {e}")
            return False
        except Exception as e:
            logger.error(f"设置ZMQ套接字时发生未知错误: {e}", exc_info=True)
            return False

    # 关闭并清理所有 ZMQ 资源
    def _close_sockets(self):
        # 按正确的顺序安全关闭，避免KeyError
        if self.poller and self.bus_socket and not getattr(self.bus_socket, 'closed', True):
            try:
                self.poller.unregister(self.bus_socket)
            except (KeyError, zmq.ZMQError):
                pass  # 如果套接字已关闭或未注册，忽略错误
        
        for sock_attr in ['sync_socket', 'bus_socket']:
            sock = getattr(self, sock_attr, None)
            if sock and not getattr(sock, 'closed', True):
                try:
                    sock.close(linger=0)
                except zmq.ZMQError:
                    pass  # 忽略关闭错误
        
        if self.context and not getattr(self.context, 'closed', True):
            try:
                self.context.term()
            except zmq.ZMQError:
                pass  # 忽略关闭错误

        self.sync_socket, self.bus_socket, self.context, self.poller = None, None, None, None

    # 与 EA 执行握手和状态同步
    def _perform_handshake(self):
        try:
            logger.info("正在与 EA 执行握手...")
            
            # 握手步骤 1: SYNC → ACK
            self.sync_socket.send_string("SYNC")
            response = self.sync_socket.recv_string()
            if response != "ACK":
                logger.warning(f"握手失败: 预期收到'ACK'，但收到'{response}'")
                return False
        
            # 握手步骤 2: 状态同步
            logger.info("正在请求 EA 的当前状态...")
            self.sync_socket.send_string("GET_STATE")
            state_json = self.sync_socket.recv_string()
            
            try:
                state_data = json.loads(state_json)
                self.state_sync_callback(state_data)
                logger.info("与 EA 的状态同步成功。")
                
                # 更新心跳和握手时间
                self.last_heartbeat_time = time.time()
                self.last_handshake_time = time.time()
                return True
            except json.JSONDecodeError as e:
                logger.error(f"无法解析EA状态JSON: {e}")
                return False
                
        except zmq.Again:
            logger.warning("握手超时: EA未在规定时间内响应")
            return False
        except zmq.ZMQError as e:
            logger.error(f"握手期间发生ZMQ错误: {e}")
            return False
        except Exception as e:
            logger.error(f"握手期间发生未知错误: {e}", exc_info=True)
            return False

    # 接收事件的主循环
    @handle_exceptions(category=ErrorCategory.TRANSIENT, re_raise=True)
    def _receive_loop(self):
        # 增加心跳超时时间，从30秒改为60秒，提高容错性
        heartbeat_timeout = self.heartbeat_timeout
        # 添加上次警告时间记录，避免频繁日志
        last_warning_time = self.last_warning_time
        
        while self.running:
            try:
                socks = dict(self.poller.poll(timeout=1000))
                if self.bus_socket in socks:
                    topic, payload = self.bus_socket.recv_multipart()
                    topic_str = topic.decode('utf-8')
                    
                    try:
                        event_dict = json.loads(payload.decode('utf-8'))
                        
                        if topic_str == "HEARTBEAT":
                            self.last_heartbeat_time = time.time()
                            logger.debug("Received EA heartbeat.")
                            event = HeartbeatEvent(timestamp=int(time.time()))
                            # 心跳事件通常不需要传递给回调
                        elif topic_str == "TRADE_EVENT":
                            # 从有效载荷中提取真正的事件类型
                            event_type = event_dict.get("event_type")
                            if not event_type:
                                logger.warning(f"收到的交易事件缺少event_type字段: {event_dict}")
                                continue
                                
                            # 创建事件对象并传递给回调
                            try:
                                # 不要修改原始event_dict，创建一个副本
                                event = create_event_from_dict(event_dict)
                                
                                # 记录详细的主账户下单信息
                                if event_type == "DEAL_ADD":
                                    is_open = event_dict.get("entry") == "IN"
                                    position_id = event_dict.get("position_id", 0)
                                    ticket = event_dict.get("ticket", 0)
                                    symbol = event_dict.get("symbol", "未知")
                                    volume = event_dict.get("volume", 0)
                                    price = event_dict.get("price", 0)
                                    profit = event_dict.get("profit", 0)
                                    trade_type = event_dict.get("type", "未知")
                                    sl = event_dict.get("sl", 0)
                                    tp = event_dict.get("tp", 0)
                                    
                                    action_type = "开仓" if is_open else "平仓"
                                    sl_str = f", 止损: {sl}" if sl > 0 else ""
                                    tp_str = f", 止盈: {tp}" if tp > 0 else ""
                                    
                                    detail_msg = (f"主账户{action_type}: 品种={symbol}, 类型={trade_type}, "
                                                f"手数={volume}, 价格={price}, 订单号={ticket}, "
                                                f"持仓ID={position_id}{sl_str}{tp_str}")
                                    logger.info(detail_msg)
                                    
                                elif event_type == "ORDER_ADD":
                                    ticket = event_dict.get("ticket", 0)
                                    symbol = event_dict.get("symbol", "未知")
                                    volume = event_dict.get("volume_initial", 0)
                                    price = event_dict.get("price_open", 0)
                                    trade_type = event_dict.get("type", "未知")
                                    sl = event_dict.get("sl", 0)
                                    tp = event_dict.get("tp", 0)
                                    
                                    sl_str = f", 止损: {sl}" if sl > 0 else ""
                                    tp_str = f", 止盈: {tp}" if tp > 0 else ""
                                    
                                    detail_msg = (f"主账户挂单: 品种={symbol}, 类型={trade_type}, "
                                                f"手数={volume}, 价格={price}, 订单号={ticket}{sl_str}{tp_str}")
                                    logger.info(detail_msg)
                                    
                                elif event_type == "POSITION_MODIFY":
                                    ticket = event_dict.get("ticket", 0)
                                    symbol = event_dict.get("symbol", "未知")
                                    sl = event_dict.get("sl", 0)
                                    tp = event_dict.get("tp", 0)
                                    
                                    sl_str = f"止损: {sl}" if sl > 0 else "无止损"
                                    tp_str = f"止盈: {tp}" if tp > 0 else "无止盈"
                                    
                                    detail_msg = (f"主账户修改持仓: 品种={symbol}, 持仓ID={ticket}, {sl_str}, {tp_str}")
                                    logger.info(detail_msg)
                                
                                logger.info(f"成功处理交易事件: {event_type} {event_dict.get('symbol', '')}")
                                self.event_callback(event)
                            except ValueError as e:
                                logger.warning(f"无法处理交易事件: {e}, 事件数据: {event_dict}")
                            except Exception as e:
                                logger.error(f"处理交易事件时发生未知错误: {e}", exc_info=True)
                        else:
                            # 直接使用主题作为事件类型
                            event_dict["event_type"] = topic_str
                            try:
                                event = create_event_from_dict(event_dict)
                                self.event_callback(event)
                            except ValueError as e:
                                logger.warning(f"无法处理事件: {e}")

                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.error(f"Failed to process incoming event. Topic: {topic_str}, "
                                    f"Payload: {payload.decode('utf-8')}, Error: {e}")
                
                # 检查心跳状态，但用更优雅的方式处理超时
                current_time = time.time()
                time_since_heartbeat = current_time - self.last_heartbeat_time
                
                # 如果超过一半的超时时间没有收到心跳，发出警告但不中断连接
                if time_since_heartbeat > self.heartbeat_warning_threshold and current_time - last_warning_time > 10:
                    logger.warning(f"已经 {time_since_heartbeat:.1f} 秒未收到EA心跳，但仍在等待...")
                    last_warning_time = current_time
                    self.last_warning_time = current_time
                    
                # 尝试主动请求心跳，增加连接容错性
                # 降低重新握手的频率，仅当超过警告阈值且距离上次握手超过60秒时才尝试
                if time_since_heartbeat > self.heartbeat_warning_threshold and current_time - self.last_handshake_time > 60:
                    logger.info("长时间未收到心跳，尝试重新握手...")
                    try:
                        # 使用非阻塞方式发送ping请求
                        if self._perform_handshake():
                            logger.info("重新握手成功，恢复连接")
                            continue
                    except Exception as e:
                        logger.error(f"尝试重新握手失败: {e}")
                
                # 只有真正超时很久才断开连接
                if time_since_heartbeat > heartbeat_timeout:
                    raise ConnectionAbortedError(f"超过 {heartbeat_timeout} 秒未收到EA心跳，连接已断开。")
            
            except zmq.Again:
                # 非阻塞操作超时，正常情况
                continue
            except ConnectionAbortedError as e:
                logger.error(f"心跳超时: {e}")
                # 不在这里关闭套接字，而是让控制循环处理重连
                return
            except zmq.ZMQError as e:
                logger.error(f"ZMQ错误: {e}")
                # 不在这里关闭套接字，而是让控制循环处理重连
                return
            except Exception as e:
                logger.error(f"接收循环中发生未知错误: {e}", exc_info=True)
                # 不在这里关闭套接字，而是让控制循环处理重连
                return