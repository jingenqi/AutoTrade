import json
import threading
from types import SimpleNamespace
import logging
import os
from typing import Optional, Dict, Any, List, Callable
import concurrent.futures
from dataclasses import dataclass, field
import time
from datetime import datetime

from .events import DealAddEvent, OrderEvent, PositionModifyEvent, BaseEvent
from .config_manager import ConfigManager
from .account_manager import AccountManager
from .constants import OrderType, TradeAction, OrderFillingType, OrderTimeType
from .error_handler import handle_exceptions, ErrorCategory, TradingErrorHandler
from .trade_history import TradeHistoryManager, TradeRecord
from .risk_manager import RiskManager

logger = logging.getLogger(f"TradeCopier.{__name__}")

@dataclass
class FollowerPosition:
    ticket: int
    symbol: str
    volume: float
    type: str
    profit: float = 0.0
    open_price: float = 0.0

@dataclass
class MasterPosition:
    ticket: int
    symbol: str
    volume: float
    type: str
    profit: float = 0.0
    open_price: float = 0.0
    followers: Dict[str, FollowerPosition] = field(default_factory=dict)

class TradeEngine:
    # 初始化交易引擎
    def __init__(self, config_manager: ConfigManager, account_manager: AccountManager, error_handler: "TradingErrorHandler"):
        self.config_manager = config_manager
        self.account_manager = account_manager
        self.error_handler = error_handler
        self.lock = threading.RLock()
        
        self.position_map: Dict[int, MasterPosition] = {}
        self.pending_order_map: Dict[str, Dict[str, int]] = {}
        
        self.position_update_callback: Optional[Callable[[List[Dict]], None]] = None
        self._load_state_from_disk()

        self._running_update_thread = False
        self._update_thread = None

        self.reverse_order_type_map = {
            "BUY": "SELL", "SELL": "BUY",
            "BUY_LIMIT": "SELL_LIMIT", "SELL_LIMIT": "BUY_LIMIT",
            "BUY_STOP": "SELL_STOP", "SELL_STOP": "BUY_STOP",
            "BUY_STOP_LIMIT": "SELL_STOP_LIMIT", "SELL_STOP_LIMIT": "BUY_STOP_LIMIT"
        }
        self.order_type_to_mt5 = {
            "BUY": OrderType.BUY, "SELL": OrderType.SELL,
            "BUY_LIMIT": OrderType.BUY_LIMIT, "SELL_LIMIT": OrderType.SELL_LIMIT,
            "BUY_STOP": OrderType.BUY_STOP, "SELL_STOP": OrderType.SELL_STOP,
            "BUY_STOP_LIMIT": OrderType.BUY_STOP_LIMIT, "SELL_STOP_LIMIT": OrderType.SELL_STOP_LIMIT
        }
        self.event_handlers = {
            "DEAL_ADD": self._handle_new_deal,
            "ORDER_ADD": self._handle_new_pending_order,
            "ORDER_UPDATE": self._handle_modify_pending_order,
            "ORDER_DELETE": self._handle_remove_pending_order,
            "POSITION_MODIFY": self._handle_position_modify
        }
        logger.info(f"TradeEngine 已初始化。当前状态包含 {len(self.position_map)} 个主仓位。")

        # 初始化交易历史和风险管理
        self.trade_history = TradeHistoryManager()
        self.risk_manager = RiskManager(config_manager)

    def start(self):
        """Starts the background threads for the trade engine."""
        self.start_profit_updater()

    def stop(self):
        """Gracefully stops the trade engine and its background threads."""
        self.stop_profit_updater()
        logger.info("TradeEngine has been stopped.")

    def start_profit_updater(self):
        if not self._running_update_thread:
            self._running_update_thread = True
            self._update_thread = threading.Thread(target=self._profit_update_loop, daemon=True)
            self._update_thread.start()
            logger.info("持仓盈亏更新线程已启动。")

    def stop_profit_updater(self):
        self._running_update_thread = False
        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=2)
        logger.info("持仓盈亏更新线程已停止。")
    
    def _profit_update_loop(self):
        while self._running_update_thread:
            try:
                self._update_all_positions_profit()
            except Exception as e:
                logger.error(f"更新持仓盈亏时发生意外错误: {e}", exc_info=True)
            
            update_interval = self.config_manager.get_setting("engine.profit_update_interval_seconds", 5)
            time.sleep(update_interval)

    @handle_exceptions(category=ErrorCategory.TRANSIENT)
    def _update_all_positions_profit(self):
        with self.lock:
            if not self.position_map:
                return # 没有持仓需要更新

            required_positions = {}
            for master_pos in self.position_map.values():
                for follower_name, follower_pos in master_pos.followers.items():
                    if follower_name not in required_positions:
                        required_positions[follower_name] = []
                    required_positions[follower_name].append(follower_pos.ticket)

            if not required_positions:
                return

        # 并行获取所有持仓的最新信息
        all_positions_info = {}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_follower = {}
            for name, tickets in required_positions.items():
                for ticket in tickets:
                    future = executor.submit(self.account_manager.get_positions, name, ticket)
                    future_to_follower[future] = (name, ticket)

            for future in concurrent.futures.as_completed(future_to_follower):
                name, ticket = future_to_follower[future]
                try:
                    result = future.result()
                    if result and result.get('status') == 'success' and result.get('positions'):
                        if name not in all_positions_info:
                            all_positions_info[name] = {}
                        all_positions_info[name][ticket] = result['positions'][0]
                except Exception as e:
                    logger.warning(f"获取账户 {name} 上的持仓 {ticket} 利润时出错: {e}")

        # 使用获取的信息更新内部状态
        with self.lock:
            profit_changed = False
            for master_pos in self.position_map.values():
                for follower_name, follower_pos in master_pos.followers.items():
                    pos_info = all_positions_info.get(follower_name, {}).get(follower_pos.ticket)
                    if pos_info:
                        new_profit = pos_info.get('profit', 0.0)
                        if follower_pos.profit != new_profit:
                            follower_pos.profit = new_profit
                            profit_changed = True
            
            # 主账户的利润可以被视为所有跟单账户利润的总和，或者另外获取
            # 为简单起见，我们暂时不聚合主账户利润
        
        if profit_changed:
            self._notify_state_change()

    # 注册一个回调函数，当状态映射变化时调用
    def register_position_update_callback(self, callback: Callable[[List[Dict]], None]):
        with self.lock:
            self.position_update_callback = callback

    # 当外部源（如EA握手）提供完整状态时，同步内部状态
    def sync_state(self, state_data: Dict[str, Any]):
        # 注意: 此函数需要适配新的MasterPosition结构，或者在EA端进行调整
        # 目前，我们将简单地清除现有状态，因为它与EA的格式不兼容
        with self.lock:
            self.position_map.clear()
            self.pending_order_map = state_data.get("pending_order_map", {}) # 挂单逻辑保持不变
            logger.info(f"交易状态已与外部源同步。清空了现有持仓映射。")
            self._save_state_to_disk()
            self._notify_state_change()

    # 获取用于UI显示的当前状态
    def get_display_state(self) -> List[Dict[str, Any]]:
        with self.lock:
            display_list = []
            for master_pos in self.position_map.values():
                display_list.append({
                    "master_symbol": master_pos.symbol,
                    "master_ticket": master_pos.ticket,
                    "master_type": master_pos.type,
                    "master_volume": master_pos.volume,
                    "master_profit": master_pos.profit,
                    "follower_positions": {
                        name: {
                            "ticket": f_pos.ticket,
                            "type": f_pos.type,
                            "volume": f_pos.volume,
                            "profit": f_pos.profit,
                        } for name, f_pos in master_pos.followers.items()
                    }
                })
            return display_list

    # 获取主账户信息 - 新增方法
    def get_master_account_info(self) -> Dict[str, Any]:
        """获取主账户信息"""
        master_config = self.config_manager.get_master_account()
        if not master_config:
            return {"name": "主账户", "balance": 0.0, "equity": 0.0, "margin": 0.0}
            
        # 尝试从第一个跟单账户获取主账户信息
        enabled_followers = self.config_manager.get_enabled_follower_configs()
        if not enabled_followers:
            return {"name": "主账户", "balance": 0.0, "equity": 0.0, "margin": 0.0}
            
        # 获取主账户持仓总数
        position_count = len(self.position_map)
        
        # 计算主账户总盈亏
        total_profit = 0.0
        for pos in self.position_map.values():
            total_profit += pos.profit
            
        return {
            "name": master_config.get("name", "主账户"),
            "balance": 0.0,  # 这些信息需要从EA获取
            "equity": 0.0,
            "margin": 0.0,
            "position_count": position_count,
            "total_profit": total_profit
        }

    # 获取格式化的持仓列表用于UI显示
    def get_formatted_positions(self) -> List[Dict[str, Any]]:
        with self.lock:
            formatted_positions = []
            for master_pos in self.position_map.values():
                position_data = {
                    "master_ticket": master_pos.ticket,
                    "symbol": master_pos.symbol,
                    "type": master_pos.type,
                    "volume": master_pos.volume,
                    "profit": master_pos.profit,
                    "open_price": master_pos.open_price,
                    "followers": {}
                }
                
                # 添加跟单账户的持仓信息
                for follower_name, follower_pos in master_pos.followers.items():
                    position_data["followers"][follower_name] = {
                        "ticket": follower_pos.ticket,
                        "volume": follower_pos.volume,
                        "type": follower_pos.type,
                        "profit": follower_pos.profit,
                        "open_price": follower_pos.open_price
                    }
                
                formatted_positions.append(position_data)
            
            return formatted_positions

    # 通知GUI状态已更新
    def _notify_state_change(self):
        if self.position_update_callback:
            try:
                display_state = self.get_display_state()
                self.position_update_callback(display_state)
            except Exception as e:
                logger.error(f"调用位置更新回调时出错: {e}", exc_info=True)

    # 从JSON文件加载交易状态
    @handle_exceptions(category=ErrorCategory.PERMANENT)
    def _load_state_from_disk(self):
        state_file = self.config_manager.get_setting("state_file", "trade_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                self.position_map = {}
                raw_pos_map = state.get("position_map", {})
                for k, v in raw_pos_map.items():
                    follower_data = v.pop("followers", {})
                    master_pos = MasterPosition(**v)
                    master_pos.followers = {
                        fname: FollowerPosition(**f_data)
                        for fname, f_data in follower_data.items()
                    }
                    self.position_map[int(k)] = master_pos

                self.pending_order_map = state.get("pending_order_map", {})
                logger.info(f"已成功从磁盘加载交易状态。找到 {len(self.position_map)} 个映射仓位。")
            except (json.JSONDecodeError, IOError, TypeError) as e:
                logger.error(f"从磁盘加载交易状态失败，将以空状态开始: {e}")
                self.position_map = {}
        else:
            logger.info("未找到交易状态文件，将以全新状态启动。")

    # 将当前交易状态保存到JSON文件
    @handle_exceptions(category=ErrorCategory.PERMANENT)
    def _save_state_to_disk(self):
        state_file = self.config_manager.get_setting("state_file", "trade_state.json")
        try:
            with self.lock:
                serializable_pos_map = {}
                for k, v in self.position_map.items():
                    master_pos_dict = v.__dict__.copy()
                    master_pos_dict['followers'] = {
                        fname: f_pos.__dict__ for fname, f_pos in v.followers.items()
                    }
                    serializable_pos_map[k] = master_pos_dict

                state = { "position_map": serializable_pos_map, "pending_order_map": self.pending_order_map }
                with open(state_file, 'w') as f:
                    json.dump(state, f, indent=4)
        except (IOError, TypeError) as e:
            logger.error(f"保存交易状态到磁盘失败: {e}")
        
        self._notify_state_change()

    # 处理单个交易事件
    @handle_exceptions(category=ErrorCategory.PERMANENT)
    def process_event(self, event: BaseEvent):
        with self.lock:
            handler = self.event_handlers.get(event.event_type)
            if handler:
                try:
                    handler(event) # Directly pass the validated event object
                except Exception as e:
                    logger.error(f"处理事件 {event.event_type} 时出错: {e}", exc_info=True)
            else:
                logger.warning(f"未找到事件类型 '{event.event_type}' 的处理器。")

    # 处理新的市价成交事件
    def _handle_new_deal(self, event: DealAddEvent):
        if event.magic != self.config_manager.get_setting("magic_number", 12345): 
            logger.debug(f"忽略非系统魔术数字的交易事件: {event.magic}")
            return

        master_position_id = event.position_id
        is_open = event.entry == 'IN'
        
        logger.info(f"处理{'开仓' if is_open else '平仓'}事件: ID={master_position_id}, 品种={event.symbol}, 类型={event.type}, 手数={event.volume}")
        
        with self.lock:
            if is_open:
                if master_position_id in self.position_map:
                    logger.warning(f"忽略重复的开仓事件: 主账户持仓ID {master_position_id} 已存在")
                    return
                
                logger.info(f"处理新开仓事件: 主账户持仓ID {master_position_id}")
                
                master_pos = MasterPosition(
                    ticket=master_position_id, symbol=event.symbol, volume=event.volume,
                    type=event.type, profit=event.profit, open_price=event.price
                )
                self.position_map[master_position_id] = master_pos
                
                requests = self._build_trade_requests(event, is_open=True)
                if not requests:
                    logger.warning(f"未能为持仓 {master_position_id} 构建任何交易请求，从映射中移除")
                    del self.position_map[master_position_id]
                    return

                logger.info(f"为新持仓 {master_position_id} 异步分发 {len(requests)} 个开仓请求")
                self.account_manager.execute_trades_parallel(list(requests.values()))
                self._save_state_to_disk() # 保存初始主仓位状态
                logger.info(f"成功分发开仓请求，主账户持仓ID: {master_position_id}")
            
            else: # 平仓逻辑
                logger.info(f"处理平仓事件: 主账户持仓ID {master_position_id}")
                
                master_pos = self.position_map.get(master_position_id)
                if not master_pos:
                    logger.warning(f"忽略平仓事件，主账户持仓ID {master_position_id} 不存在")
                    return

                follower_positions = {name: pos.ticket for name, pos in master_pos.followers.items()}
                
                if not follower_positions:
                    logger.warning(f"主持仓 {master_position_id} 没有关联的跟单持仓，无需平仓")
                    del self.position_map[master_position_id]
                    self._save_state_to_disk()
                    return
                    
                requests = self._build_trade_requests(event, is_open=False, follower_positions=follower_positions)
                
                if not requests: 
                    logger.warning(f"未能为持仓 {master_position_id} 构建任何平仓请求")
                    return

                results = self.account_manager.execute_trades_parallel(list(requests.values()))
                
                for follower_name, result in results.items():
                    if result and result.get('status') == 'success':
                        logger.info(f"[{follower_name}] 平仓成功: master_id={master_position_id}")
                        if master_position_id in self.position_map:
                            if follower_name in self.position_map[master_position_id].followers:
                                del self.position_map[master_position_id].followers[follower_name]
                            if not self.position_map[master_position_id].followers:
                                del self.position_map[master_position_id]
                    else:
                        retcode = result.get('payload', {}).get('result', {}).get('retcode')
                        error_msg = result.get('payload', {}).get('result', {}).get('comment', f'retcode={retcode}')
                        logger.error(f"[{follower_name}] 平仓失败: {error_msg}")
                
                self._save_state_to_disk()

    # 处理止损/止盈修改事件
    def _handle_position_modify(self, event: PositionModifyEvent):
        master_position_id = event.ticket
        logger.info(f"处理持仓修改事件: 主账户持仓ID {master_position_id}")
        with self.lock:
            master_pos = self.position_map.get(master_position_id)
            if not master_pos:
                logger.warning(f"无法找到要修改的持仓 {master_position_id}")
                return
            follower_positions = {name: pos.ticket for name, pos in master_pos.followers.items()}
        
        if not follower_positions:
            logger.info(f"持仓 {master_position_id} 没有跟单者，无需修改")
            return

        requests = self._build_modify_requests(event, follower_positions)
        if requests:
            logger.info(f"为 {len(requests)} 个跟单持仓构建了修改请求")
            self.account_manager.execute_trades_parallel(requests)

    # 处理新的挂单事件
    def _handle_new_pending_order(self, event: OrderEvent):
        logger.info(f"处理新挂单事件 (功能暂未完全实现): {event.ticket}")
        requests = self._build_pending_order_requests(event, "ADD")
        if not requests: return
        
        # This part should be async in the future
        results = self.account_manager.execute_trades_parallel(list(requests.values()))
        with self.lock:
            master_order_id = str(event.ticket)
            self.pending_order_map[master_order_id] = {}
            for name, result in results.items():
                if result and result.get("status") == "success":
                    res_payload = result.get('payload', {})
                    if res_payload and res_payload.get('result'):
                        self.pending_order_map[master_order_id][name] = res_payload['result'].get('order')
            self._save_state_to_disk()

    # 处理挂单修改事件
    def _handle_modify_pending_order(self, event: OrderEvent):
        logger.info(f"处理挂单修改事件 (功能暂未完全实现): {event.ticket}")
        master_order_id = str(event.ticket)
        with self.lock:
            follower_orders = self.pending_order_map.get(master_order_id)
            if not follower_orders: return
        requests = self._build_pending_order_requests(event, "MODIFY", follower_orders)
        if requests:
            self.account_manager.execute_trades_parallel(list(requests.values()))

    # 处理挂单移除事件
    def _handle_remove_pending_order(self, event: OrderEvent):
        logger.info(f"处理挂单移除事件 (功能暂未完全实现): {event.ticket}")
        master_order_id = str(event.ticket)
        with self.lock:
            follower_orders = self.pending_order_map.get(master_order_id)
            if not follower_orders: return
        
        requests = self._build_pending_order_requests(event, "DELETE", follower_orders)
        if requests:
            self.account_manager.execute_trades_parallel(list(requests.values()))
            with self.lock:
                if master_order_id in self.pending_order_map:
                    del self.pending_order_map[master_order_id]
                    self._save_state_to_disk()

    # 构建开仓或平仓的市价单请求
    def _build_trade_requests(self, event: DealAddEvent, is_open: bool, follower_positions: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        trade_requests = {}
        enabled_followers = self.config_manager.get_enabled_follower_configs()
        if not enabled_followers: 
            logger.warning("没有启用的跟单账户，无法构建交易请求")
            return {}
        
        logger.info(f"开始为 {len(enabled_followers)} 个已启用账户构建{'开仓' if is_open else '平仓'}请求...")
        
        master_symbol = event.symbol
        
        master_info = None
        for follower_name in enabled_followers:
            if follower_name in self.account_manager.task_queues:
                temp_info = self.account_manager.get_symbol_info(follower_name, master_symbol)
                if temp_info:
                    master_info = temp_info
                    logger.debug(f"从账户 {follower_name} 获取到主品种 {master_symbol} 的信息")
                    break
        
        if not master_info:
            logger.warning(f"无法从任何跟单账户获取主品种 {master_symbol} 的信息，使用默认点值")
            master_point = 0.00001
        else:
            master_point = master_info.get('point', 0.00001)

        required_symbols = {
            name: config.get("symbol_mapping", {}).get(master_symbol, master_symbol)
            for name, config in enabled_followers.items()
            if name in self.account_manager.task_queues
        }
            
        if not required_symbols:
            logger.error("没有可用的跟单账户工作进程来获取品种信息")
            return {}
            
        all_symbol_infos = self._get_symbol_info_from_workers(required_symbols)
        
        all_follower_pos_info = {}
        if not is_open and follower_positions:
            all_follower_pos_info = self._get_positions_from_workers(follower_positions)

        for name, config in enabled_followers.items():
            if name not in self.account_manager.task_queues:
                continue
                
            symbol_info_ns = all_symbol_infos.get(name)
            if not symbol_info_ns: 
                logger.error(f"账户 '{name}' 无法获取品种 '{required_symbols.get(name)}' 的信息，跳过交易请求构建。")
                continue
                
            symbol_info = symbol_info_ns.__dict__
            
            if symbol_info.get('point', 0.0) == 0.0:
                logger.error(f"账户 '{name}' 的品种 '{symbol_info['name']}' 点值为0，无法计算滑点，跳过。")
                continue

            request_base = {
                "magic": self.config_manager.get_setting("magic_number", 12345), 
                "account_name": name,
                "master_position_id": event.position_id
            }
            
            if is_open:
                lot_size = self._calculate_lot_size(name, config, event, symbol_info, master_point)
                if lot_size <= 0:
                    logger.warning(f"跟单账户 {name}: 计算出的手数为 {lot_size}，无效。跳过此交易。")
                    continue
                    
                trade_type, sl, tp = self._get_trade_params(config, event, symbol_info, master_point)
                deviation = int(config.get("max_slippage_pips", 3) / symbol_info['point'])

                request = {
                    **request_base, "action": TradeAction.DEAL.value, "symbol": symbol_info['name'],
                    "volume": lot_size, "type": self.order_type_to_mt5[trade_type].value,
                    "price": event.price, "deviation": deviation,
                    "sl": sl, "tp": tp, "comment": "跟单",
                    "type_time": OrderTimeType.GTC.value, "type_filling": OrderFillingType.IOC.value,
                }
                trade_requests[name] = request
                logger.info(f"为账户 '{name}' 构建开仓请求: 品种={symbol_info['name']}, 类型={trade_type}, 手数={lot_size}, 滑点={deviation}点")
            else: #平仓
                follower_ticket = follower_positions.get(name)
                if not follower_ticket: 
                    continue

                pos_list = all_follower_pos_info.get(name, {}).get(follower_ticket)
                if not pos_list: 
                    logger.warning(f"账户 '{name}' 无法获取持仓 {follower_ticket} 的信息，跳过平仓请求构建")
                    continue

                follower_pos = pos_list
                close_type = OrderType.SELL if follower_pos['type'] == OrderType.BUY.value else OrderType.BUY
                deviation = int(config.get("max_slippage_pips", 3) / symbol_info['point'])
                
                request = {
                    **request_base, "action": TradeAction.DEAL.value, "symbol": follower_pos['symbol'],
                    "volume": follower_pos['volume'], "type": close_type.value,
                    "position": follower_pos['ticket'], "price": event.price,
                    "deviation": deviation,
                    "type_time": OrderTimeType.GTC.value, "type_filling": OrderFillingType.IOC.value,
                }
                trade_requests[name] = request
                logger.info(f"为账户 '{name}' 构建平仓请求: 持仓ID={follower_pos['ticket']}, 品种={follower_pos['symbol']}, 手数={follower_pos['volume']}")
        
        logger.info(f"构建了 {len(trade_requests)} 个交易请求")
        return trade_requests

    # 构建修改现有持仓止损/止盈的请求
    def _build_modify_requests(self, event: PositionModifyEvent, follower_positions: Dict[str, int]) -> List[Dict]:
        requests = []
        enabled_followers = self.config_manager.get_enabled_follower_configs()
        if not enabled_followers: return []
        
        first_follower_with_worker = next((name for name in enabled_followers if name in self.account_manager.task_queues), None)
        if not first_follower_with_worker: 
            logger.warning("没有带工作进程的跟单账户，无法获取主账户品种信息")
            return []

        master_info_ns = self.account_manager.get_symbol_info(first_follower_with_worker, event.symbol)
        if not master_info_ns: return []
        master_point = master_info_ns.get('point', 0.00001)
        
        flat_follower_positions = {name: ticket for name, ticket in follower_positions.items()}
        follower_pos_infos_map = self._get_positions_from_workers(flat_follower_positions)

        required_symbols = {
            name: pos['symbol'] 
            for name, pos_map in follower_pos_infos_map.items() 
            for ticket, pos in pos_map.items()
        }

        follower_symbol_infos_ns = self._get_symbol_info_from_workers(required_symbols)

        for name, pos_id in follower_positions.items():
            config = enabled_followers.get(name)
            if not config or not config.get("copy_sl_tp", True): continue
            
            f_pos = follower_pos_infos_map.get(name, {}).get(pos_id)
            if not f_pos: continue
            
            f_sym_info_ns = follower_symbol_infos_ns.get(name)
            if not f_sym_info_ns: continue

            new_sl, new_tp = self._calculate_sl_tp_for_follower(config, event, f_pos, master_point, f_sym_info_ns.point)
            
            logger.info(f"为账户 {name} 构建修改请求: 仓位 {pos_id}, 新SL={new_sl}, 新TP={new_tp}")
            
            requests.append({
                "action": TradeAction.SLTP.value, "position": pos_id,
                "sl": new_sl, "tp": new_tp,
                "magic": self.config_manager.get_setting("magic_number", 12345),
                "account_name": name
            })
        return requests

    # 构建添加、修改或删除挂单的请求
    def _build_pending_order_requests(self, event: OrderEvent, action: str, follower_orders: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        requests = {}
        enabled_followers = self.config_manager.get_enabled_follower_configs()
        if not enabled_followers: return {}
        
        logger.info(f"开始构建挂单请求, action: {action}, 主订单: {event.ticket}")

        master_symbol = event.symbol
        first_follower_with_worker = next((name for name in enabled_followers if name in self.account_manager.task_queues), None)
        if not first_follower_with_worker:
            logger.warning("没有可用的跟单账户来获取主品种信息")
            return {}
            
        master_info = self.account_manager.get_symbol_info(first_follower_with_worker, master_symbol)
        master_point = master_info.get('point', 0.00001) if master_info else 0.00001

        required_symbols = {
            n: c.get("symbol_mapping", {}).get(master_symbol, master_symbol) 
            for n, c in enabled_followers.items() 
            if n in self.account_manager.task_queues
        }
        all_symbol_infos_ns = self._get_symbol_info_from_workers(required_symbols)

        for name, config in enabled_followers.items():
            if name not in self.account_manager.task_queues: continue
            
            request_base = {"magic": self.config_manager.get_setting("magic_number", 12345), "account_name": name}
            f_ord_id = follower_orders.get(name) if follower_orders else None
            
            if action == "DELETE":
                if f_ord_id: 
                    requests[name] = {**request_base, "action": TradeAction.REMOVE.value, "order": f_ord_id}
                    logger.info(f"为账户 {name} 构建删除挂单请求: 订单号={f_ord_id}")
                continue

            symbol_info_ns = all_symbol_infos_ns.get(name)
            if not symbol_info_ns: 
                logger.error(f"账户 {name} 无法获取品种信息，跳过挂单请求")
                continue

            symbol_info = symbol_info_ns.__dict__
            if symbol_info.get('point', 0.0) == 0.0:
                logger.error(f"账户 '{name}' 的品种 '{symbol_info['name']}' 点值为0，跳过")
                continue

            lot_size = self._calculate_lot_size(name, config, event, symbol_info, master_point)
            if lot_size <= 0:
                logger.warning(f"跟单账户 {name}: 挂单计算手数为 {lot_size}，无效，跳过")
                continue

            trade_type, sl, tp = self._get_trade_params(config, event, symbol_info, master_point)
            deviation = int(config.get("max_slippage_pips", 3) / symbol_info['point'])

            request = {
                **request_base, "symbol": symbol_info['name'], "volume": lot_size,
                "type": self.order_type_to_mt5[trade_type].value, "price": event.price_open,
                "deviation": deviation,
                "sl": sl, "tp": tp, "comment": "跟单",
                "type_time": OrderTimeType.GTC.value, "type_filling": OrderFillingType.IOC.value,
            }

            if action == "ADD":
                request["action"] = TradeAction.PENDING.value
                requests[name] = request
                logger.info(f"为账户 {name} 构建新挂单请求: 类型={trade_type}, 手数={lot_size}")
            elif action == "MODIFY" and f_ord_id:
                request["action"] = TradeAction.MODIFY.value
                request["order"] = f_ord_id
                requests[name] = request
                logger.info(f"为账户 {name} 构建修改挂单请求: 订单号={f_ord_id}")
        
        logger.info(f"构建了 {len(requests)} 个挂单请求")
        return requests

    # 并行从工作进程获取品种信息
    def _get_symbol_info_from_workers(self, required_symbols: Dict[str, str]) -> Dict[str, SimpleNamespace]:
        infos = {}
        
        # 过滤掉没有工作进程的账户
        valid_symbols = {}
        for name, symbol in required_symbols.items():
            if name in self.account_manager.task_queues:
                valid_symbols[name] = symbol
                logger.info(f"准备获取账户 '{name}' 的品种 '{symbol}' 信息")
            else:
                logger.warning(f"账户 '{name}' 没有工作进程，跳过品种信息获取")
                infos[name] = None
        
        if not valid_symbols:
            logger.error("没有有效的账户可以获取品种信息")
            return infos
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(valid_symbols)) as executor:
            future_to_follower = {
                executor.submit(self.account_manager.get_symbol_info, name, symbol): (name, symbol) 
                for name, symbol in valid_symbols.items()
            }
            
            for future in concurrent.futures.as_completed(future_to_follower):
                follower_name, symbol = future_to_follower[future]
                try:
                    info_dict = future.result()
                    if info_dict:
                        infos[follower_name] = SimpleNamespace(**info_dict)
                        logger.info(f"成功获取账户 '{follower_name}' 的品种 '{symbol}' 信息")
                    else:
                        infos[follower_name] = None
                        logger.error(f"账户 '{follower_name}' 返回空的品种信息，请检查品种 '{symbol}' 是否存在")
                except Exception as exc:
                    logger.error(f"为账户 '{follower_name}' 获取品种 '{symbol}' 信息时出错: {exc}", exc_info=True)
                    infos[follower_name] = None
                    
        return infos

    # 并行从工作进程获取持仓信息
    def _get_positions_from_workers(self, required_positions: Dict[str, int]) -> Dict[str, Dict[int, Dict]]:
        positions = {}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_follower = { executor.submit(self.account_manager.get_positions, name, ticket): (name, ticket) for name, ticket in required_positions.items() }
            for future in concurrent.futures.as_completed(future_to_follower):
                follower_name, ticket = future_to_follower[future]
                try:
                    result = future.result()
                    if result and result.get('status') == 'success' and result.get('positions'):
                        if follower_name not in positions:
                            positions[follower_name] = {}
                        positions[follower_name][ticket] = result['positions'][0]

                except Exception as exc:
                    logger.error(f"为账户 {follower_name} 获取持仓信息时出错: {exc}", exc_info=True)
        return positions

    # 为跟单账户计算合适的交易手数
    def _calculate_lot_size(self, follower_name, follower_config, event, symbol_info, master_point):
        lot_mode = follower_config.get("lot_mode", "multiplier")
        lot_size = 0.0
        
        # 获取主账户交易量
        master_volume = event.volume if isinstance(event, DealAddEvent) else event.volume_initial
        
        if lot_mode == "risk_percentage":
            if isinstance(event, DealAddEvent):
                 lot_size = self._calculate_risk_based_lot_size(follower_name, event, follower_config, symbol_info, master_point)
            else:
                logger.warning(f"跟单账户 {follower_name}: 挂单不支持风险百分比模式，使用固定手数。")
                lot_size = follower_config.get("lot_value", 0.01)
        elif lot_mode == "multiplier":
            multiplier = follower_config.get("lot_value", 1.0)
            lot_size = master_volume * multiplier
            logger.info(f"跟单账户 {follower_name}: 使用倍数 {multiplier} on master volume {master_volume} -> lots: {lot_size}")
        else: # fixed lot
            lot_size = follower_config.get("lot_value", 0.01)
            logger.info(f"跟单账户 {follower_name}: 使用固定手数: {lot_size}")
        
        if lot_size is None or lot_size <= 0: 
            return 0.0
            
        # 确保手数在有效范围内
        lot_size = max(symbol_info['volume_min'], min(lot_size, symbol_info['volume_max']))
        
        # 修正手数以符合步进大小
        volume_step = symbol_info.get('volume_step', 0.01)
        if volume_step > 0:
            lot_size = round(lot_size / volume_step) * volume_step
            # 由于浮点数精度问题，再次进行格式化
            lot_size = float(f"{lot_size:.{len(str(volume_step).split('.')[-1])}f}")

        return lot_size

    # 根据跟单策略决定交易参数
    def _get_trade_params(self, follower_config, event, symbol_info, master_point):
        trade_type_str = event.type
        sl, tp = event.sl, event.tp
        if follower_config.get("strategy") == "reverse":
            trade_type_str = self.reverse_order_type_map.get(trade_type_str, trade_type_str)
            if sl > 0 or tp > 0:
                price = event.price if isinstance(event, DealAddEvent) else event.price_open
                order_type_val = self.order_type_to_mt5[trade_type_str].value
                sl, tp = self._calculate_reversed_sl_tp(order_type_val, price, sl, tp, symbol_info['point'] / master_point if master_point > 0 else 1.0)
            else:
                sl, tp = 0.0, 0.0
        return trade_type_str, sl, tp

    # 为跟单仓位计算止损/止盈
    def _calculate_sl_tp_for_follower(self, follower_config, event, follower_position, master_point, follower_point):
        point_ratio = follower_point / master_point if master_point > 0 else 1.0
        if follower_config.get("strategy") == "reverse":
            return self._calculate_reversed_sl_tp(follower_position['type'], follower_position['price_open'], event.sl, event.tp, point_ratio)
        else:
            new_sl, new_tp = 0.0, 0.0
            if event.sl > 0:
                master_sl_points = abs(event.price_open - event.sl) / master_point
                new_sl = follower_position['price_open'] - (master_sl_points * follower_point) if follower_position['type'] == OrderType.BUY.value else follower_position['price_open'] + (master_sl_points * follower_point)
            if event.tp > 0:
                master_tp_points = abs(event.tp - event.price_open) / master_point
                new_tp = follower_position['price_open'] + (master_tp_points * follower_point) if follower_position['type'] == OrderType.BUY.value else follower_position['price_open'] - (master_tp_points * follower_point)
            return new_sl, new_tp

    # 为反向交易计算镜像的止损/止盈
    def _calculate_reversed_sl_tp(self, order_type_val, open_price, master_sl, master_tp, point_ratio=1.0):
        new_sl, new_tp = 0.0, 0.0
        is_sell_type = order_type_val in [OrderType.SELL.value, OrderType.SELL_LIMIT.value, OrderType.SELL_STOP.value, OrderType.SELL_STOP_LIMIT.value]
        if master_tp > 0:
            master_sl_dist = abs(open_price - master_tp)
            new_sl = open_price + master_sl_dist * point_ratio if is_sell_type else open_price - master_sl_dist * point_ratio
        if master_sl > 0:
            master_tp_dist = abs(open_price - master_sl)
            new_tp = open_price - master_tp_dist * point_ratio if is_sell_type else open_price + master_tp_dist * point_ratio
        return new_sl, new_tp

    # 根据账户余额的风险百分比计算手数
    def _calculate_risk_based_lot_size(self, follower_name, event, follower_config, symbol_info, master_point):
        risk_percentage = follower_config.get("lot_value", 1.0)
        account_info_payload = self.account_manager.get_account_info(follower_name)
        if not account_info_payload or not account_info_payload.get("info"): return None
        balance = account_info_payload["info"].get("balance")
        if not balance: return None
        
        sl_price = event.sl
        if sl_price == 0:
            logger.warning(f"无法为账户 {follower_name} 计算基于风险的手数，因为主交易没有止损。")
            return None

        price = event.price if isinstance(event, DealAddEvent) else event.price_open
        point_ratio = symbol_info['point'] / master_point if master_point > 0 else 1.0
        sl_dist_points = abs(price - sl_price) / master_point
        follower_sl_dist_currency = sl_dist_points * symbol_info['point'] * point_ratio
        
        if follower_sl_dist_currency == 0 or symbol_info['trade_tick_value'] == 0:
            logger.warning(f"无法为账户 {follower_name} 计算基于风险的手数，止损距离或点值为零。")
            return None
            
        risk_amount = balance * (risk_percentage / 100.0)
        lot_size = risk_amount / (follower_sl_dist_currency * symbol_info['trade_tick_value'])
        return lot_size

    def handle_trade_result(self, result: Dict[str, Any]):
        """
        Handles trade results coming from the asynchronous callback.
        NOTE: This is currently a placeholder. The main trade logic is synchronous.
        """
        logger.info(f"Trade result received by callback (currently not processed in main logic): {result}")
        # In a future refactor, the logic from _execute_and_process_trades
        # should be moved here to make the trade flow fully asynchronous.
        pass

    def __del__(self):
        # 对象销毁时安全地停止线程，但不记录日志
        self._running_update_thread = False