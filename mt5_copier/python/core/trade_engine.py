import json
import threading
# from pydantic import ValidationError
import MetaTrader5 as mt5
import logging
import os
from typing import Optional, Dict, Any
import time

# 直接从python目录开始导入
from core.events import DealAddEvent, OrderEvent, PositionModifyEvent
from core.config_manager import ConfigManager
from core.account_manager import AccountManager

# 设置日志
logger = logging.getLogger("TradeCopier.TradeEngine")

# 添加MT5 API兼容性处理
def get_order_filling_type():
    """
    获取MT5 API中支持的订单填充类型常量
    不同版本的MT5 API可能使用不同的常量名称(ORDER_FILL_* vs ORDER_FILLING_*)
    """
    # 首先尝试新版API的常量名称
    if hasattr(mt5, 'ORDER_FILLING_FOK'):
        logger.debug("使用ORDER_FILLING_FOK常量")
        return mt5.ORDER_FILLING_FOK
    elif hasattr(mt5, 'ORDER_FILLING_IOC'):
        logger.debug("使用ORDER_FILLING_IOC常量")
        return mt5.ORDER_FILLING_IOC
    # 再尝试旧版API的常量名称
    elif hasattr(mt5, 'ORDER_FILL_FOK'):
        logger.debug("使用ORDER_FILL_FOK常量")
        return mt5.ORDER_FILL_FOK
    elif hasattr(mt5, 'ORDER_FILL_IOC'):
        logger.debug("使用ORDER_FILL_IOC常量")
        return mt5.ORDER_FILL_IOC
    # 如果都不存在，使用数字常量(1通常代表IOC, 2通常代表FOK)
    else:
        logger.warning("MT5 API没有提供订单填充类型常量，使用默认值1(IOC)")
        return 1  # 默认使用IOC(IMMEDIATE_OR_CANCEL)方式

# 定义订单填充类型常量
ORDER_FILLING_TYPE = get_order_filling_type()

class TradeEngine:
    # 交易应用程序的核心逻辑单元。它处理接收到的交易事件，应用交易策略逻辑，并与 AccountManager 协调执行交易。

    STATE_FILE = "logs/trade_state.json"

    def __init__(self, config_manager: ConfigManager, account_manager: AccountManager):
        # 初始化 TradeEngine。
        # Args:
        #     config_manager: ConfigManager 的实例。
        #     account_manager: AccountManager 的实例。
        self.config_manager = config_manager
        self.account_manager = account_manager
        # 用于跟踪主账户和跟单账户之间关系的映射
        self.position_map: dict = {}  # {master_position_id: {follower_name: follower_position_id}}
        self.pending_order_map: dict = {}  # {master_order_id: {follower_name: follower_order_id}}
        self.lock = threading.RLock()
        
        # 用于通知GUI持仓更新的回调
        self.position_update_callback = None

        # 反向策略的订单类型映射
        self.reverse_order_type_map = {
            "BUY": "SELL",
            "SELL": "BUY",
            "BUY_LIMIT": "SELL_STOP",
            "SELL_LIMIT": "BUY_STOP",
            "BUY_STOP": "SELL_LIMIT",
            "SELL_STOP": "BUY_LIMIT",
            "BUY_STOP_LIMIT": "SELL_STOP_LIMIT",
            "SELL_STOP_LIMIT": "BUY_STOP_LIMIT"
        }

        # MT5 订单类型字符串到常量映射
        self.order_type_to_mt5 = {
            "BUY": mt5.ORDER_TYPE_BUY,
            "SELL": mt5.ORDER_TYPE_SELL,
            "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
            "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
            "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
            "BUY_STOP_LIMIT": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
            "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT
        }

        self.event_handlers = {
            "DEAL_ADD": self._handle_deal_add,
            "ORDER_ADD": self._handle_order_add,
            "ORDER_UPDATE": self._handle_order_update,
            "ORDER_DELETE": self._handle_order_delete,
            "POSITION_MODIFY": self._handle_position_modify,
        }

        self._load_state_from_disk()
        logger.info(f"TradeEngine 已初始化。当前状态包含 {len(self.position_map)} 个主仓位。")

    def _save_state_to_disk(self):
        # 将当前的持仓和订单映射保存到文件以实现持久化。
        with self.lock:
            try:
                state_data = {
                    "position_map": self.position_map,
                    "pending_order_map": self.pending_order_map,
                }
                # 确保日志目录存在
                os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
                with open(self.STATE_FILE, "w", encoding='utf-8') as f:
                    json.dump(state_data, f, indent=2, ensure_ascii=False)
                logger.debug("已成功将交易状态保存到磁盘。")
            except Exception as e:
                logger.error(f"保存状态到磁盘失败: {e}", exc_info=True)

    def _load_state_from_disk(self):
        # 在初始化时从文件加载交易状态。
        with self.lock:
            if not os.path.exists(self.STATE_FILE):
                logger.info("未找到状态文件。将以干净状态启动。")
                return

            try:
                with open(self.STATE_FILE, "r", encoding='utf-8') as f:
                    state_data = json.load(f)
                    self.position_map = state_data.get("position_map", {})
                    self.pending_order_map = state_data.get("pending_order_map", {})
                    logger.info(f"已成功从磁盘加载交易状态。找到 {len(self.position_map)} 个映射仓位。")
            except Exception as e:
                logger.error(f"从磁盘加载状态失败，将重新开始: {e}", exc_info=True)
                self.position_map = {}
                self.pending_order_map = {}

    def sync_state(self, state: dict):
        # 将引擎的状态与主账户的当前状态同步。在成功（重新）连接到 EA 后调用此方法。
        # 它会清除现有映射并根据 EA 的实时数据重建它们。
        # Args:
        #     state (dict): 包含来自 EA 的 'positions' 和 'orders' 的字典。
        with self.lock:
            logger.info("正在与主账户同步状态...")
            
            # --- 1. 保存现有映射的备份，以便在需要时恢复 ---
            old_position_map = self.position_map.copy()
            old_pending_order_map = self.pending_order_map.copy()
            
            # --- 2. 清除现有跟踪映射 ---
            self.position_map.clear()
            self.pending_order_map.clear()
            logger.debug("已清除现有持仓和订单映射。")

            # --- 3. 从主账户获取当前持仓和订单 ---
            master_positions = state.get('positions', [])
            master_orders = state.get('orders', [])

            logger.info(f"主账户状态: {len(master_positions)} 个未平仓头寸, {len(master_orders)} 个挂单。")
            
            # --- 4. 尝试恢复现有持仓的映射 ---
            if master_positions and old_position_map:
                logger.info("尝试恢复持仓映射关系...")
                # 将主账户持仓转换为字典，方便查找
                master_pos_dict = {str(pos.get('ticket', 0)): pos for pos in master_positions}
                
                # 检查旧映射中的每个主仓位是否仍然存在
                for master_pos_id, follower_positions in old_position_map.items():
                    if master_pos_id in master_pos_dict:
                        # 主仓位仍然存在，保留映射
                        self.position_map[master_pos_id] = follower_positions
                        logger.info(f"恢复了主仓位 {master_pos_id} 的映射: {follower_positions}")
                
                logger.info(f"持仓映射恢复完成。恢复了 {len(self.position_map)}/{len(old_position_map)} 个映射。")
            
            # --- 5. 尝试恢复挂单的映射 ---
            if master_orders and old_pending_order_map:
                logger.info("尝试恢复挂单映射关系...")
                # 将主账户挂单转换为字典，方便查找
                master_order_dict = {str(order.get('ticket', 0)): order for order in master_orders}
                
                # 检查旧映射中的每个主挂单是否仍然存在
                for master_order_id, follower_orders in old_pending_order_map.items():
                    if master_order_id in master_order_dict:
                        # 主挂单仍然存在，保留映射
                        self.pending_order_map[master_order_id] = follower_orders
                        logger.info(f"恢复了主挂单 {master_order_id} 的映射: {follower_orders}")
                
                logger.info(f"挂单映射恢复完成。恢复了 {len(self.pending_order_map)}/{len(old_pending_order_map)} 个映射。")
            
            # 保存恢复后的状态
            self._save_state_to_disk()
            
            logger.info("状态同步完成。引擎已准备好处理新事件。")
    
    def _calculate_risk_based_lot_size(self, follower_name: str, event: DealAddEvent, 
                                     follower_config: dict, symbol_info, master_point: float) -> Optional[float]:
        """
        根据风险百分比计算交易手数。
        
        Args:
            follower_name: 跟单账户名称
            event: 交易事件
            follower_config: 账户配置
            symbol_info: 跟单账户的交易品种信息
            master_point: 主账户交易品种的点值
            
        Returns:
            计算出的手数，如果无法计算则返回 None
        """
        account_info = self.account_manager.get_account_info(follower_name)
        if not account_info:
            logger.warning(f"跟单账户 {follower_name}: 无法获取账户信息。")
            return None
            
        balance = account_info.balance
        risk_percentage = follower_config.get("risk_percentage", 0.01)  # 默认 1%
        
        # 检查止损是否设置
        if event.sl <= 0 or event.price <= 0:
            lot_size = follower_config.get("lot_value", 0.01)
            logger.warning(f"跟单账户 {follower_name}: 无止损，使用固定手数 {lot_size}。")
            return lot_size
            
        # 计算风险金额
        risk_amount = balance * risk_percentage
        
        # 计算止损距离（以点为单位）
        sl_distance_price = abs(event.price - event.sl)
        sl_distance_points = sl_distance_price / symbol_info.point
        
        if sl_distance_points <= 0:
            logger.warning(f"跟单账户 {follower_name}: 止损距离为零，无法计算风险手数。")
            return follower_config.get("lot_value", 0.01)
            
        # 获取每手每点的价值
        # 使用 tick_value 和 tick_size 来计算每点价值
        point_value_per_lot = (symbol_info.point / symbol_info.tick_size) * symbol_info.tick_value
        
        # 对于某些品种（如指数），可能需要使用合约规模
        contract_size = getattr(symbol_info, 'trade_contract_size', 100000)
        
        # 计算每手的风险金额
        risk_per_lot = sl_distance_points * point_value_per_lot
        
        if risk_per_lot <= 0:
            logger.warning(f"跟单账户 {follower_name}: 每手风险计算为零或负数。")
            return follower_config.get("lot_value", 0.01)
            
        # 计算手数
        lot_size = risk_amount / risk_per_lot
        
        # 标准化手数
        lot_size = self._normalize_lot_size(lot_size, symbol_info)
        
        logger.info(f"跟单账户 {follower_name}: 基于 {risk_percentage*100:.2f}% 风险计算的手数为 {lot_size:.2f}。"
                   f" (风险金额: {risk_amount:.2f}, 止损距离: {sl_distance_points:.1f} 点)")
        
        return lot_size
        
    def _normalize_lot_size(self, lot_size: float, symbol_info) -> float:
        """
        标准化手数以符合交易品种的要求。
        
        Args:
            lot_size: 原始手数
            symbol_info: 交易品种信息
            
        Returns:
            标准化后的手数
        """
        # 确保手数在允许范围内
        lot_size = max(symbol_info.volume_min, min(lot_size, symbol_info.volume_max))
        
        # 调整手数以符合步进大小
        volume_step = symbol_info.volume_step
        if volume_step > 0:
            lot_size = round(lot_size / volume_step) * volume_step
            
        return lot_size

    def _get_symbol_info(self, follower_name: str, symbol: str) -> Optional[Any]:
        """
        安全地获取交易品种信息，如果需要，会自动尝试启用该品种。
        如果无法获取品种信息，会返回一个默认的品种信息对象，以确保交易流程不会中断。
        """
        # 获取跟单账户配置
        follower_config = self.config_manager.get_follower_config(follower_name)
        if not follower_config:
            logger.warning(f"无法获取账户 {follower_name} 的配置")
            return None
            
        # 检查该账户的品种映射
        symbol_mapping = follower_config.get("symbol_mapping", {})
        # 查看主品种到跟单品种的映射
        mapped_symbol = symbol_mapping.get(symbol, symbol)
        if mapped_symbol != symbol:
            logger.info(f"跟单账户 {follower_name}: 品种 {symbol} 已映射到 {mapped_symbol}")
            symbol = mapped_symbol

        # 第一次尝试获取映射后的品种信息
        info = mt5.symbol_info(symbol)
        if info:
            logger.debug(f"跟单账户 {follower_name}: 成功获取 {symbol} 的信息")
            return info

        # 如果失败，尝试启用该品种并重试
        logger.warning(f"跟单账户 {follower_name}: 无法直接获取 {symbol} 的信息，尝试启用它...")
        if mt5.symbol_select(symbol, True):
            # 等待一小段时间让终端处理请求
            time.sleep(0.1) 
            info = mt5.symbol_info(symbol)
            if info:
                logger.info(f"跟单账户 {follower_name}: 成功启用并获取了 {symbol} 的信息。")
                return info
        
        # 如果仍然失败，检查是否有备用的映射方案或格式不同的相同品种
        logger.warning(f"跟单账户 {follower_name}: 无法获取交易品种 {symbol} 的信息，尝试查找替代品种...")
        
        # 尝试从终端获取所有可交易品种
        available_symbols = mt5.symbols_get()
        if available_symbols:
            available_symbol_names = [s.name for s in available_symbols]
            logger.debug(f"跟单账户 {follower_name}: 可用交易品种: {', '.join(available_symbol_names[:10])}...")
            
            # 检查品种是否有不同的大小写或格式版本
            symbol_lower = symbol.lower()
            for avail_sym in available_symbol_names:
                if avail_sym.lower() == symbol_lower:
                    logger.info(f"跟单账户 {follower_name}: 找到大小写不同的品种 {avail_sym}，将使用它代替 {symbol}")
                    info = mt5.symbol_info(avail_sym)
                    if info:
                        return info
        
        logger.error(f"跟单账户 {follower_name}: 无法获取交易品种 {symbol} 的信息，即使在多次尝试后。")
        logger.error(f"请确保在账户配置中正确设置了品种映射，或检查该品种是否存在于您的经纪商处。")
        
        # 返回一个基本的默认品种信息对象，防止系统崩溃
        # 注意：这只是一个应急方案，实际交易将可能出错
        from types import SimpleNamespace
        default_info = SimpleNamespace()
        default_info.name = symbol
        default_info.point = 0.00001  # 默认点值，通常适用于外汇对
        default_info.volume_min = 0.01
        default_info.volume_max = 100.0
        default_info.volume_step = 0.01
        default_info.tick_size = 0.00001
        default_info.tick_value = 1.0
        logger.warning(f"跟单账户 {follower_name}: 使用默认品种信息进行交易。这可能导致交易错误。")
        
        return default_info

    def process_event(self, event_data: Dict[str, Any]):
        """
        处理来自上游的单个交易事件字典。
        它会验证负载，将其转换为强类型的事件模型，然后分派到相应的处理程序。
        """
        try:
            event_type = event_data.get("event_type")
            if not event_type:
                logger.warning(f"接收到缺少 event_type 的事件: {event_data}")
                return

            logger.debug(f"正在处理事件类型: {event_type}, 数据: {event_data}")

            handler = self.event_handlers.get(event_type)
            if handler:
                # Pydantic models will raise validation error if data is bad
                if event_type == "DEAL_ADD":
                    handler(DealAddEvent(**event_data))
                elif event_type in ("ORDER_ADD", "ORDER_UPDATE", "ORDER_DELETE"):
                    handler(OrderEvent(**event_data))
                elif event_type == "POSITION_MODIFY":
                    handler(PositionModifyEvent(**event_data))
            else:
                logger.warning(f"未知事件类型 '{event_type}'，正在忽略。")

        except Exception as e: # 在Pydantic模型验证失败时也会捕捉到
            logger.error(f"处理事件时发生错误: {e}", exc_info=True)

    def _handle_deal_add(self, event: DealAddEvent):
        """处理新的成交事件。"""
        with self.lock:
            # 对于反向 (INOUT) 交易，我们必须先平仓现有仓位，然后开立新仓位。
            if event.entry == "INOUT":
                logger.info(f"正在处理反向 (INOUT) 仓位: deal={event.ticket}, position={event.position_id}")
                # 首先平仓旧仓位，使用合成平仓事件
                self._close_positions(event)
                # 然后开立新仓位
                self._open_positions(event)

            elif event.entry == "IN":
                logger.info(f"正在处理开仓: deal={event.ticket}, position={event.position_id}")
                self._open_positions(event)

            elif event.entry in ["OUT", "OUT_BY"]:
                logger.info(f"正在处理平仓: deal={event.ticket}, position={event.position_id}")
                self._close_positions(event)
            
            else:
                logger.warning(f"交易 {event.ticket} 的交易入场类型 '{event.entry}' 不受支持。")
                
        # 更新GUI持仓信息
        self.update_positions()

    def _handle_order_add(self, event: OrderEvent):
        # 处理 ORDER_ADD 事件 - 新订单（市价单或挂单）。
        # 对于状态为 "STARTED" 的市价单，我们通常等待 DEAL_ADD 事件。
        # 对于挂单，我们需要创建相应的挂单。
        if event.state == "PLACED" and event.price_open > 0:
            # 这是一个挂单
            self._handle_new_pending_order(event)
        # 状态为 "STARTED" 的市价单将由 DEAL_ADD 处理

    def _handle_order_update(self, event: OrderEvent):
        """处理 ORDER_UPDATE 事件 - 修改现有订单。"""
        # 同样，只关心挂单的修改
        if event.type in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"):
            self._handle_modify_pending_order(event)

    def _handle_order_delete(self, event: OrderEvent):
        """处理 ORDER_DELETE 事件 - 订单取消。"""
        if event.type in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP", "BUY_STOP_LIMIT", "SELL_STOP_LIMIT"):
            self._handle_delete_pending_order(event)

    def _handle_position_modify(self, event: PositionModifyEvent):
        """处理止损/止盈修改事件。"""
        with self.lock:
            master_position_id_str = str(event.position_id)
            follower_positions = self.position_map.get(master_position_id_str, {})

            if not follower_positions:
                logger.info(f"未找到主仓位 {master_position_id_str} 的跟单仓位进行修改。")
                return

            # 获取主账户交易品种的点值
            master_symbol_info = mt5.symbol_info(event.symbol)
            if not master_symbol_info:
                logger.error(f"无法获取主账户品种 {event.symbol} 的信息")
                return
            master_point = master_symbol_info.point

            for follower_name, follower_position_id in follower_positions.items():
                try:
                    follower_config = self.config_manager.get_follower_config(follower_name)
                    
                    # 检查是否同步SL/TP
                    if not follower_config.get("copy_sl_tp", True):
                        logger.info(f"跟单账户 {follower_name} 配置为不同步SL/TP，跳过修改")
                        continue
                    
                    # 获取跟单账户持仓信息
                    follower_positions_info = mt5.positions_get(ticket=follower_position_id)
                    if not follower_positions_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取持仓 {follower_position_id} 的信息")
                        continue
                        
                    follower_position = follower_positions_info[0]
                    follower_symbol = follower_position.symbol
                    follower_symbol_info = mt5.symbol_info(follower_symbol)
                    if not follower_symbol_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取品种 {follower_symbol} 的信息")
                        continue
                        
                    follower_point = follower_symbol_info.point
                    
                    # 计算点值比率用于调整SL/TP
                    point_ratio = follower_point / master_point if master_point > 0 else 1.0
                    
                    new_sl = 0
                    new_tp = 0
                    
                    # 根据跟单策略计算新的SL/TP
                    if follower_config.get("reverse_trades", False):
                        # 反向跟单 - 需要"镜像"计算SL/TP
                        new_sl, new_tp = self._calculate_reversed_sl_tp(
                            follower_position.type, 
                            follower_position.price_open,
                            event.sl, 
                            event.tp, 
                            point_ratio
                        )
                    else:
                        # 正向跟单 - 保持相对距离
                        # 如果主账户有止损
                        if event.sl > 0:
                            # 计算主账户止损点数距离
                            if event.type == "BUY":
                                # 买入: 止损在下方
                                master_sl_points = (event.price_open - event.sl) / master_point
                                new_sl = follower_position.price_open - (master_sl_points * follower_point)
                            else:
                                # 卖出: 止损在上方
                                master_sl_points = (event.sl - event.price_open) / master_point
                                new_sl = follower_position.price_open + (master_sl_points * follower_point)
                        
                        # 如果主账户有止盈
                        if event.tp > 0:
                            # 计算主账户止盈点数距离
                            if event.type == "BUY":
                                # 买入: 止盈在上方
                                master_tp_points = (event.tp - event.price_open) / master_point
                                new_tp = follower_position.price_open + (master_tp_points * follower_point)
                            else:
                                # 卖出: 止盈在下方
                                master_tp_points = (event.price_open - event.tp) / master_point
                                new_tp = follower_position.price_open - (master_tp_points * follower_point)
                    
                    # 构建修改请求
                    request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": follower_position_id,
                        "sl": new_sl,
                        "tp": new_tp,
                        "magic": self.config_manager.EA_MAGIC
                    }
                    
                    # 执行请求
                    result = self.account_manager.execute_single_trade(follower_name, request)
                    
                    if result and result.get("status") == "success":
                        logger.info(f"跟单账户 {follower_name}: 成功修改持仓 {follower_position_id} 的SL/TP")
                    else:
                        logger.error(f"跟单账户 {follower_name}: 修改持仓 {follower_position_id} 的SL/TP失败: {result}")
                        
                except Exception as e:
                    logger.error(f"跟单账户 {follower_name}: 修改SL/TP时发生错误: {e}", exc_info=True)
            
            # 更新GUI持仓信息
            self.update_positions()

    def _handle_new_pending_order(self, event: OrderEvent):
        # 处理新的挂单事件。为每个跟单账户构建挂单请求。
        trade_requests = self._build_pending_order_requests(event, "ADD")
        if not trade_requests:
            logger.info("未生成新挂单请求。")
            return

        results = self.account_manager.execute_trades_parallel(trade_requests)

        with self.lock:
            for name, result in results.items():
                if result and result.get("status") == "success":
                    follower_order_ticket = result["result"].order
                    self.pending_order_map[str(event.ticket)] = self.pending_order_map.get(str(event.ticket), {})
                    self.pending_order_map[str(event.ticket)][name] = follower_order_ticket
                    self._save_state_to_disk()
                    logger.info(f"为 {name} 成功创建挂单 {follower_order_ticket} 并保存状态。")
                else:
                    logger.error(f"为 {name} 创建挂单失败: {result}")

    def _handle_modify_pending_order(self, event: OrderEvent):
        # 处理修改现有挂单的事件。需要实现更高级的逻辑来判断是否是价格、SL/TP 或其他修改。
        with self.lock:
            master_position_id = str(event.ticket)
            follower_positions = self.position_map.get(master_position_id, {})

            if not follower_positions:
                logger.info(f"未找到主仓位 {master_position_id} 的跟单仓位进行修改。")
                return

            # 获取主账户交易品种的点值
            master_symbol_info = mt5.symbol_info(event.symbol)
            if not master_symbol_info:
                logger.error(f"无法获取主账户品种 {event.symbol} 的信息")
                return
            master_point = master_symbol_info.point

            for follower_name, follower_position_id in follower_positions.items():
                try:
                    follower_config = self.config_manager.get_follower_config(follower_name)
                    
                    # 检查是否同步SL/TP
                    if not follower_config.get("copy_sl_tp", True):
                        logger.info(f"跟单账户 {follower_name} 配置为不同步SL/TP，跳过修改")
                        continue
                    
                    # 获取跟单账户持仓信息
                    follower_positions_info = mt5.positions_get(ticket=follower_position_id)
                    if not follower_positions_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取持仓 {follower_position_id} 的信息")
                        continue
                        
                    follower_position = follower_positions_info[0]
                    follower_symbol = follower_position.symbol
                    follower_symbol_info = mt5.symbol_info(follower_symbol)
                    if not follower_symbol_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取品种 {follower_symbol} 的信息")
                        continue
                        
                    follower_point = follower_symbol_info.point
                    
                    # 计算点值比率用于调整SL/TP
                    point_ratio = follower_point / master_point if master_point > 0 else 1.0
                    
                    new_sl = 0
                    new_tp = 0
                    
                    # 根据跟单策略计算新的SL/TP
                    if follower_config.get("reverse_trades", False):
                        # 反向跟单 - 需要"镜像"计算SL/TP
                        new_sl, new_tp = self._calculate_reversed_sl_tp(
                            follower_position.type, 
                            follower_position.price_open,
                            event.sl, 
                            event.tp, 
                            point_ratio
                        )
                    else:
                        # 正向跟单 - 保持相对距离
                        # 如果主账户有止损
                        if event.sl > 0:
                            # 计算主账户止损点数距离
                            if event.type == "BUY":
                                # 买入: 止损在下方
                                master_sl_points = (event.price_open - event.sl) / master_point
                                new_sl = follower_position.price_open - (master_sl_points * follower_point)
                            else:
                                # 卖出: 止损在上方
                                master_sl_points = (event.sl - event.price_open) / master_point
                                new_sl = follower_position.price_open + (master_sl_points * follower_point)
                        
                        # 如果主账户有止盈
                        if event.tp > 0:
                            # 计算主账户止盈点数距离
                            if event.type == "BUY":
                                # 买入: 止盈在上方
                                master_tp_points = (event.tp - event.price_open) / master_point
                                new_tp = follower_position.price_open + (master_tp_points * follower_point)
                            else:
                                # 卖出: 止盈在下方
                                master_tp_points = (event.price_open - event.tp) / master_point
                                new_tp = follower_position.price_open - (master_tp_points * follower_point)
                    
                    # 构建修改请求
                    request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "position": follower_position_id,
                        "sl": new_sl,
                        "tp": new_tp,
                        "magic": self.config_manager.EA_MAGIC
                    }
                    
                    # 执行请求
                    result = self.account_manager.execute_single_trade(follower_name, request)
                    
                    if result and result.get("status") == "success":
                        logger.info(f"跟单账户 {follower_name}: 成功修改持仓 {follower_position_id} 的SL/TP")
                    else:
                        logger.error(f"跟单账户 {follower_name}: 修改持仓 {follower_position_id} 的SL/TP失败: {result}")
                        
                except Exception as e:
                    logger.error(f"跟单账户 {follower_name}: 修改SL/TP时发生错误: {e}", exc_info=True)

    def _handle_delete_pending_order(self, event: OrderEvent):
        # 处理删除挂单事件。
        with self.lock:
            master_order_id = str(event.ticket)
            follower_orders = self.pending_order_map.pop(master_order_id, {})

            if not follower_orders:
                logger.info(f"未找到主订单 {master_order_id} 的跟单挂单进行删除。")
                return

            trade_requests = self._build_pending_order_requests(event, "DELETE", follower_orders)
            if not trade_requests:
                logger.info("未生成删除挂单请求。")
                return

            results = self.account_manager.execute_trades_parallel(trade_requests)

            for name, result in results.items():
                if result and result.get("status") == "success":
                    logger.info(f"为 {name} 成功删除挂单。")
                else:
                    logger.error(f"为 {name} 删除挂单失败: {result}")

            self._save_state_to_disk()
            logger.info(f"已为所有跟单账户删除挂单 {master_order_id} 并保存状态。")

    def _open_positions(self, event: DealAddEvent):
        # 处理跟单账户的开仓。包括风险管理和滑点控制。
        # 1. 构建请求（此方法现在需要更智能）
        trade_requests = self._build_trade_requests(event, is_open=True)
        if not trade_requests:
            logger.info("未生成交易请求。")
            return

        # 2. 执行交易
        results = self.account_manager.execute_trades_parallel(trade_requests)

        # 3. 处理结果，检查滑点，并更新映射
        with self.lock:
            master_position_id_str = str(event.position_id)
            logger.debug(f"主账户开仓: position_id={master_position_id_str}, symbol={event.symbol}, volume={event.volume}")
            
            # 确保在字典中有该主仓位的条目
            if master_position_id_str not in self.position_map:
                self.position_map[master_position_id_str] = {}
                
            for name, result in results.items():
                if result and result.get("status") == "success":
                    follower_result = result["result"]
                    # 滑点检查
                    follower_config = self.config_manager.get_follower_config(name)
                    max_slippage = follower_config.get("max_slippage_pips", 3) if follower_config else 3
                    
                    # 获取订单号
                    follower_position_id = follower_result.order
                    
                    # 确保订单号有效
                    if follower_position_id > 0:
                        # 更新映射并保存状态
                        self.position_map[master_position_id_str][name] = follower_position_id
                        logger.info(f"为 {name} 成功开仓 {follower_position_id} 并映射到主仓位 {master_position_id_str}")
                    else:
                        logger.warning(f"跟单账户 {name} 的订单号无效: {follower_position_id}")
                        
                    # 保存状态到磁盘
                    self._save_state_to_disk()
                    
                    # 记录当前映射状态，用于调试
                    logger.debug(f"当前持仓映射: {self.position_map}")
                else:
                    error_msg = result.get("message", "未知错误") if result else "交易结果为空"
                    logger.error(f"为 {name} 开仓失败: {error_msg}")
                    
            # 更新GUI持仓信息
            self.update_positions()

    def _close_positions(self, event: DealAddEvent):
        # 处理跟单账户的平仓。
        # Args:
        #     event: DealAddEvent (或包含 position_id 的任何事件)
        with self.lock:
            master_position_id = str(event.position_id)
            logger.debug(f"主账户平仓: position_id={master_position_id}, symbol={event.symbol}, volume={event.volume}")
            logger.debug(f"当前持仓映射: {self.position_map}")
            
            # 获取并移除映射中的跟单仓位
            follower_positions = self.position_map.pop(master_position_id, {})

            if not follower_positions:
                logger.warning(f"未找到主仓位 {master_position_id} 的跟单仓位进行平仓。可能的原因：")
                logger.warning(f"1. 该主仓位未被成功复制")
                logger.warning(f"2. 仓位映射丢失或未正确保存")
                logger.warning(f"3. 该仓位已经被平仓")
                return

            logger.info(f"找到主仓位 {master_position_id} 的 {len(follower_positions)} 个跟单仓位需要平仓: {follower_positions}")
            
            # 构建平仓请求
            trade_requests = {}
            
            # 对每个跟单账户单独处理
            for follower_name, follower_position_id in follower_positions.items():
                # 获取跟单账户的连接
                mt5_conn = self.account_manager._get_connection(follower_name)
                if not mt5_conn:
                    logger.error(f"无法连接到跟单账户 {follower_name} 进行平仓")
                    continue
                
                try:
                    # 直接获取跟单仓位信息
                    position_info = mt5_conn.positions_get(ticket=follower_position_id)
                    
                    if not position_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取仓位 {follower_position_id} 的信息，可能已被手动平仓")
                        continue
                    
                    # 获取仓位信息成功，构建平仓请求
                    position = position_info[0]
                    
                    # 获取交易品种信息
                    symbol_info = mt5_conn.symbol_info(position.symbol)
                    if not symbol_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取交易品种 {position.symbol} 的信息")
                        # 使用默认值继续
                    
                    # 构建平仓请求
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": position.symbol,
                        "volume": position.volume,
                        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                        "position": follower_position_id,
                        "price": mt5_conn.symbol_info_tick(position.symbol).bid if position.type == mt5.POSITION_TYPE_BUY else mt5_conn.symbol_info_tick(position.symbol).ask,
                        "deviation": 300000,  # 使用大偏差值确保执行
                        "magic": self.config_manager.EA_MAGIC,
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": ORDER_FILLING_TYPE,
                    }
                    
                    trade_requests[follower_name] = request
                    logger.debug(f"为 {follower_name} 构建平仓请求: {request}")
                    
                except Exception as e:
                    logger.error(f"跟单账户 {follower_name}: 构建平仓请求时出错: {e}")
                finally:
                    # 释放连接
                    self.account_manager._release_connection(mt5_conn)
            
            if not trade_requests:
                logger.info("未生成平仓交易请求。")
                return

            # 执行平仓
            results = self.account_manager.execute_trades_parallel(trade_requests)

            # 处理结果并从映射中移除已平仓位
            success_count = 0
            for name, result in results.items():
                if result and result.get("status") == "success":
                    logger.info(f"为 {name} 成功平仓跟单仓位 {follower_positions.get(name)}。")
                    success_count += 1
                else:
                    error_msg = result.get("message", "未知错误") if result else "交易结果为空"
                    logger.error(f"为 {name} 平仓失败: {error_msg}")
            
            # 保存状态
            self._save_state_to_disk()
            logger.info(f"已为主仓位 {master_position_id} 成功平仓 {success_count}/{len(follower_positions)} 个跟单仓位。")
            
            # 更新GUI持仓信息
            self.update_positions()

    def _build_trade_requests(self, event: DealAddEvent, is_open: bool, is_modify: bool = False, follower_positions: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        # 构建要发送给 AccountManager 的交易请求。
        # Args:
        #     event: 触发交易的 DealAddEvent 或 PositionModifyEvent。
        #     is_open: 如果是开仓请求则为 True，否则为 False。
        #     is_modify: 如果是修改现有仓位则为 True。
        #     follower_positions: 如果是平仓或修改，则为主仓位对应的跟单仓位。
        # Returns:
        #     映射账户名称到其交易请求字典的字典。
        trade_requests = {}
        master_symbol = event.symbol

        # 获取主账户的点值大小，用于反向策略的SL/TP计算
        master_symbol_info = mt5.symbol_info(master_symbol)
        if not master_symbol_info:
            # 注意：此处的mt5连接是上一个操作留下的，可能不是主账户的。
            # 这是一个理论上的风险，但在当前单线程处理事件模型下风险较低。
            # 更安全的做法是为EA也建立一个专用的连接通道。
            logger.warning(f"无法获取主账户交易品种 {master_symbol} 的信息，反向策略的SL/TP计算可能不准。")
            master_point = 0.00001 # 假设一个默认值
        else:
            master_point = master_symbol_info.point

        for follower_name, follower_config in self.config_manager.get_enabled_follower_configs().items():
            
            # 1. 确定跟单账户的交易品种
            # 首先检查是否有特定的品种映射
            follower_symbol = follower_config.get("symbol_mapping", {}).get(master_symbol, master_symbol)
            
            # 2. 获取跟单账户的品种信息
            # 使用健壮的方法获取品种信息
            symbol_info = self._get_symbol_info(follower_name, follower_symbol)
            if not symbol_info:
                logger.error(f"跟单账户 {follower_name}: 无法获取或创建品种 {follower_symbol} 的信息，跳过此账户的交易")
                continue # 跳过此跟单账户

            # 3. 计算交易手数
            lot_mode = follower_config.get("lot_mode", "multiplier")
            if lot_mode == "risk_percentage":
                # 基于风险百分比计算手数
                lot_size = self._calculate_risk_based_lot_size(
                    follower_name, event, follower_config, symbol_info, master_point
                )
                if lot_size is None:
                    continue
            elif lot_mode == "multiplier":
                # 基于倍数的手数计算
                multiplier = follower_config.get("lot_value", 1.0)
                lot_size = event.volume * multiplier
                logger.info(f"跟单账户 {follower_name}: 使用倍数 {multiplier} 计算手数，结果为 {lot_size}。")
            else: # 固定手数
                lot_size = follower_config.get("lot_value", 0.01)
                logger.info(f"跟单账户 {follower_name}: 使用固定手数 {lot_size}。")

            # 确保手数在有效范围内
            lot_size = max(symbol_info.volume_min, min(lot_size, symbol_info.volume_max))
            # 调整手数以符合步进大小
            lot_size = round(lot_size / symbol_info.volume_step) * symbol_info.volume_step
            
            if lot_size <= 0:
                logger.warning(f"跟单账户 {follower_name}: 计算出的手数为 {lot_size}，无效。跳过此交易。")
                continue

            trade_type = event.type
            price = event.price
            sl = event.sl
            tp = event.tp
            comment = "跟单"  

            # 应用反向交易策略
            if follower_config.get("reverse_trades", False):
                trade_type = self.reverse_order_type_map.get(trade_type, trade_type)
                logger.info(f"跟单账户 {follower_name}: 应用反向交易策略。新类型: {trade_type}")
                
                # 反转 SL/TP (如果适用且有意义)
                if (sl > 0 or tp > 0) and follower_config.get("copy_reversed_sl_tp", True):
                    # 根据反向交易策略计算新的SL/TP
                    reversed_order_type = self.order_type_to_mt5.get(trade_type, mt5.ORDER_TYPE_BUY)
                    sl, tp = self._calculate_reversed_sl_tp(
                        reversed_order_type,
                        price,
                        sl,
                        tp,
                        symbol_info.point / master_point if master_point > 0 else 1.0
                    )
                    logger.info(f"跟单账户 {follower_name}: 已反转SL/TP值。新值: SL={sl}, TP={tp}")
                else:
                    # 如果不需要复制SL/TP或没有设置
                    sl = 0
                    tp = 0

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol_info.name,
                "volume": lot_size,
                "type": self.order_type_to_mt5.get(trade_type, mt5.ORDER_TYPE_BUY), # 默认 BUY
                "price": price,
                "deviation": int(follower_config.get("max_slippage_pips", 3) / symbol_info.point), # 将点差转换为 MT5 偏差
                "sl": sl,
                "tp": tp,
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC, # Good Till Cancel
                "type_filling": ORDER_FILLING_TYPE,
                "magic": self.config_manager.EA_MAGIC,
            }

            if is_open:
                logger.debug(f"为 {follower_name} 构建开仓请求: {request}")
                trade_requests[follower_name] = request
            elif is_modify:
                # 对于修改，我们需要知道跟单仓位 ID
                follower_position_id = follower_positions.get(follower_name)
                if follower_position_id:
                    request["action"] = mt5.TRADE_ACTION_SLTP # 专门用于修改 SL/TP
                    request["position"] = follower_position_id
                    # 修改请求不需要 volume, type, price, deviation, type_time, type_filling
                    del request["volume"]
                    del request["type"]
                    del request["price"]
                    del request["deviation"]
                    del request["type_time"]
                    del request["type_filling"]
                    logger.debug(f"为 {follower_name} 构建修改头寸请求: {request}")
                    trade_requests[follower_name] = request
                else:
                    logger.warning(f"跟单账户 {follower_name}: 未找到要修改的跟单仓位。跳过。")
            else: # 平仓
                follower_position_id = follower_positions.get(follower_name)
                if follower_position_id:
                    # 获取跟单仓位信息以确定平仓方向
                    follower_pos_info = mt5.positions_get(ticket=follower_position_id)
                    if follower_pos_info:
                        follower_pos = follower_pos_info[0] # positions_get 返回元组
                        # 平仓操作使用相反的类型
                        close_type = mt5.ORDER_TYPE_SELL if follower_pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                        request = {
                            "action": mt5.TRADE_ACTION_DEAL,
                            "symbol": symbol_info.name,
                            "volume": follower_pos.volume,
                            "type": close_type,
                            "position": follower_position_id,
                            "price": price,
                            "deviation": int(follower_config.get("max_slippage_pips", 3) / symbol_info.point),
                            "magic": self.config_manager.EA_MAGIC,
                            "type_time": mt5.ORDER_TIME_GTC,
                            "type_filling": ORDER_FILLING_TYPE,
                        }
                        logger.debug(f"为 {follower_name} 构建平仓请求: {request}")
                        trade_requests[follower_name] = request
                    else:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取跟单仓位 {follower_position_id} 的信息。跳过平仓。")
                else:
                    logger.warning(f"跟单账户 {follower_name}: 未找到要平仓的跟单仓位。跳过。")

        return trade_requests

    def _build_pending_order_requests(self, event: OrderEvent, action: str, follower_orders: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        # 根据订单事件构建挂单请求。
        # Args:
        #     event: 触发请求的 OrderEvent。
        #     action: "ADD", "MODIFY", "DELETE"。
        #     follower_orders: 现有跟单挂单的映射（仅用于 MODIFY/DELETE）。
        # Returns:
        #     映射账户名称到其交易请求字典的字典。
        order_requests = {}
        master_symbol = event.symbol

        # 获取主账户的点值大小，用于反向策略的SL/TP计算
        master_symbol_info = mt5.symbol_info(master_symbol)
        if not master_symbol_info:
            # 注意：此处的mt5连接是上一个操作留下的，可能不是主账户的。
            # 这是一个理论上的风险，但在当前单线程处理事件模型下风险较低。
            # 更安全的做法是为EA也建立一个专用的连接通道。
            logger.warning(f"无法获取主账户交易品种 {master_symbol} 的信息，反向策略的SL/TP计算可能不准。")
            master_point = 0.00001 # 假设一个默认值
        else:
            master_point = master_symbol_info.point

        for follower_name, follower_config in self.config_manager.get_enabled_follower_configs().items():
            try:
                # 确定跟单账户的交易品种
                # 首先检查是否有特定的品种映射
                symbol = follower_config.get("symbol_mapping", {}).get(master_symbol, master_symbol)
                
                # 获取跟单账户的品种信息
                # 使用健壮的方法获取品种信息
                follower_symbol_info = self._get_symbol_info(follower_name, symbol)
                if follower_symbol_info is None:
                    logger.error(f"跟单账户 {follower_name}: 无法获取或创建品种 {symbol} 的信息，跳过此账户的交易")
                    continue
                follower_point = follower_symbol_info.point

                # 跟单手数计算与开仓逻辑类似，但需针对挂单场景调整
                lot_mode = follower_config.get("lot_mode", "fixed")
                if lot_mode == "risk_percentage":
                    # 挂单的风险计算更复杂，因为它依赖于未来的开仓价格。
                    # 暂时，我们假设在挂单时不计算风险，直接使用固定手数，或者在市价单时应用风险。
                    lot_size = follower_config.get("lot_value", 0.01)
                    logger.warning(f"跟单账户 {follower_name}: 挂单不支持风险百分比模式，使用固定手数 {lot_size}。")
                elif lot_mode == "multiplier":
                    # 基于倍数的手数计算
                    multiplier = follower_config.get("lot_value", 1.0)
                    lot_size = event.volume * multiplier
                    logger.info(f"跟单账户 {follower_name}: 使用倍数 {multiplier} 计算手数，结果为 {lot_size}。")
                else: # 固定手数
                    lot_size = follower_config.get("lot_value", 0.01)

                # 确保手数在有效范围内
                lot_size = max(follower_symbol_info.volume_min, min(lot_size, follower_symbol_info.volume_max))
                lot_size = round(lot_size / follower_symbol_info.volume_step) * follower_symbol_info.volume_step

                if lot_size <= 0:
                    logger.warning(f"跟单账户 {follower_name}: 计算出的手数为 {lot_size}，无效。跳过此订单。")
                    continue

                order_type = event.type
                price_open = event.price_open
                sl = event.sl
                tp = event.tp
                comment = "跟单"  

                # 应用反向交易策略 (针对挂单类型)
                if follower_config.get("reverse_trades", False):
                    order_type = self.reverse_order_type_map.get(order_type, order_type)
                    logger.info(f"跟单账户 {follower_name}: 应用反向交易策略。新类型: {order_type}")
                    
                    # 反转 SL/TP (如果适用)
                    if (sl > 0 or tp > 0) and follower_config.get("copy_reversed_sl_tp", True):
                        # 根据反向交易策略计算新的SL/TP
                        reversed_order_type = self.order_type_to_mt5.get(order_type, mt5.ORDER_TYPE_BUY_LIMIT)
                        sl, tp = self._calculate_reversed_sl_tp(
                            reversed_order_type,
                            price_open,
                            sl,
                            tp,
                            follower_point / master_point if master_point > 0 else 1.0
                        )
                        logger.info(f"跟单账户 {follower_name}: 已反转挂单SL/TP值。新值: SL={sl}, TP={tp}")
                    else:
                        # 如果不需要复制SL/TP或没有设置
                        sl = 0
                        tp = 0

                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": symbol,
                    "volume": lot_size,
                    "type": self.order_type_to_mt5.get(order_type, mt5.ORDER_TYPE_BUY_LIMIT), # 默认 BUY_LIMIT
                    "price": price_open,
                    "deviation": int(follower_config.get("max_slippage_pips", 3) / follower_point),
                    "sl": sl,
                    "tp": tp,
                    "comment": comment,
                    "type_time": mt5.ORDER_TIME_GTC, 
                    "type_filling": ORDER_FILLING_TYPE, 
                    "magic": self.config_manager.EA_MAGIC,
                }
                
                if action == "ADD":
                    logger.debug(f"为 {follower_name} 构建新挂单请求: {request}")
                    order_requests[follower_name] = request
                elif action == "MODIFY":
                    follower_order_ticket = follower_orders.get(follower_name)
                    if follower_order_ticket:
                        request["action"] = mt5.TRADE_ACTION_MODIFY 
                        request["order"] = follower_order_ticket
                        del request["volume"]
                        del request["type"]
                        del request["deviation"]
                        del request["type_time"]
                        del request["type_filling"]
                        logger.debug(f"为 {follower_name} 构建修改挂单请求: {request}")
                        order_requests[follower_name] = request
                    else:
                        logger.warning(f"跟单账户 {follower_name}: 未找到要修改的跟单挂单。跳过。")
                elif action == "DELETE":
                    follower_order_ticket = follower_orders.get(follower_name)
                    if follower_order_ticket:
                        request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": follower_order_ticket,
                            "magic": self.config_manager.EA_MAGIC,
                        }
                        logger.debug(f"为 {follower_name} 构建删除挂单请求: {request}")
                        order_requests[follower_name] = request
                    else:
                        logger.warning(f"跟单账户 {follower_name}: 未找到要删除的跟单挂单。跳过。")
            except Exception as e:
                logger.error(f"为跟单账户 {follower_name} 构建挂单请求失败: {e}", exc_info=True)
                continue

        return order_requests 

    def _calculate_reversed_sl_tp(self, position_type, open_price, master_sl, master_tp, point_ratio=1.0):
        """
        为反向交易计算镜像的止损止盈位置
        
        Args:
            position_type: 跟单持仓类型 (mt5.ORDER_TYPE_BUY 或 mt5.ORDER_TYPE_SELL)
            open_price: 跟单持仓的开仓价格
            master_sl: 主账户的止损价格
            master_tp: 主账户的止盈价格
            point_ratio: 点值比率 (follower_point / master_point)
        
        Returns:
            (new_sl, new_tp): 计算后的止损和止盈价格
        """
        # 如果原始SL/TP都为0，不设置新的SL/TP
        if master_sl <= 0 and master_tp <= 0:
            return 0, 0
        
        new_sl = 0
        new_tp = 0
        
        # 反转SL/TP逻辑：止损变止盈，止盈变止损
        # 买入变为卖出：开仓价格上方的止盈变为下方的止损，下方的止损变为上方的止盈
        # 卖出变为买入：开仓价格下方的止盈变为上方的止损，上方的止损变为下方的止盈
        if position_type == mt5.ORDER_TYPE_BUY:
            # 跟单是买入 (主账户应该是卖出)
            if master_tp > 0:  # 主账户的TP (下方) 变为跟单账户的SL (下方)
                # 计算点数距离并应用点值比率
                distance_points = (open_price - master_tp) * point_ratio
                new_sl = open_price - distance_points
            
            if master_sl > 0:  # 主账户的SL (上方) 变为跟单账户的TP (上方)
                distance_points = (master_sl - open_price) * point_ratio
                new_tp = open_price + distance_points
        else:
            # 跟单是卖出 (主账户应该是买入)
            if master_tp > 0:  # 主账户的TP (上方) 变为跟单账户的SL (上方)
                distance_points = (master_tp - open_price) * point_ratio
                new_sl = open_price + distance_points
            
            if master_sl > 0:  # 主账户的SL (下方) 变为跟单账户的TP (下方)
                distance_points = (open_price - master_sl) * point_ratio
                new_tp = open_price - distance_points
        
        return new_sl, new_tp 

    def register_position_update_callback(self, callback):
        """注册持仓更新回调函数"""
        self.position_update_callback = callback
        
    def update_positions(self):
        """更新并发送持仓信息到GUI"""
        if not self.position_update_callback:
            return
            
        try:
            positions_data = []
            with self.lock:
                for master_id, followers in self.position_map.items():
                    # 获取主账户持仓信息
                    master_pos = None
                    try:
                        # 尝试通过MT5 API获取主账户持仓详情
                        master_pos_info = mt5.positions_get(ticket=int(master_id))
                        if master_pos_info:
                            master_pos = master_pos_info[0]
                    except Exception as e:
                        logger.warning(f"获取主账户持仓 {master_id} 信息失败: {e}")
                    
                    position_data = {
                        "master_ticket": master_id,
                        "master_symbol": "未知",
                        "master_volume": 0.0,
                        "master_profit": 0.0,
                        "master_type": "未知",
                        "follower_positions": {}
                    }
                    
                    if master_pos:
                        position_data.update({
                            "master_symbol": master_pos.symbol,
                            "master_volume": master_pos.volume,
                            "master_profit": master_pos.profit,
                            "master_type": "BUY" if master_pos.type == mt5.ORDER_TYPE_BUY else "SELL"
                        })
                    
                    # 获取跟单账户持仓信息
                    for follower_name, follower_id in followers.items():
                        if not isinstance(follower_id, (int, float)):
                            continue
                            
                        follower_data = {
                            "ticket": follower_id,
                            "volume": 0.0,
                            "profit": 0.0,
                            "type": "未知"
                        }
                        
                        try:
                            # 使用账户管理器安全地获取持仓信息
                            mt5_conn = self.account_manager._get_connection(follower_name)
                            if mt5_conn:
                                try:
                                    follower_pos_info = mt5_conn.positions_get(ticket=int(follower_id))
                                    if follower_pos_info:
                                        follower_pos = follower_pos_info[0]
                                        follower_data.update({
                                            "volume": follower_pos.volume,
                                            "profit": follower_pos.profit,
                                            "type": "BUY" if follower_pos.type == mt5.ORDER_TYPE_BUY else "SELL"
                                        })
                                finally:
                                    # 释放连接
                                    self.account_manager._release_connection(mt5_conn)
                        except Exception as e:
                            logger.warning(f"获取跟单账户 {follower_name} 持仓 {follower_id} 信息失败: {e}")
                        
                        position_data["follower_positions"][follower_name] = follower_data
                    
                    positions_data.append(position_data)
            
            # 调用回调函数发送持仓数据
            if self.position_update_callback:
                self.position_update_callback(positions_data)
                
        except Exception as e:
            logger.error(f"更新持仓信息失败: {e}", exc_info=True) 