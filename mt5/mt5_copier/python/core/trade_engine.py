import json
import threading
# from pydantic import ValidationError
import MetaTrader5 as mt5
import logging
import os
from typing import Optional, Dict, Any

from core.events import DealAddEvent, OrderEvent, PositionModifyEvent
from core.config_manager import ConfigManager
from core.account_manager import AccountManager

# 设置日志
logger = logging.getLogger("TradeCopier.TradeEngine")

class TradeEngine:
    # 交易应用程序的核心逻辑单元。它处理接收到的交易事件，应用交易策略逻辑，并与 AccountManager 协调执行交易。

    STATE_FILE = "trade_state.json"

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
            
            # --- 1. 清除现有跟踪映射 ---
            self.position_map.clear()
            self.pending_order_map.clear()
            logger.debug("已清除现有持仓和订单映射。")

            # --- 2. 根据跟单账户配置重新填充映射 ---
            # 这是一个简化的逻辑。更健壮的实现会查询跟单账户以查找匹配的交易，
            # 但目前，我们假设如果复制器正在运行，则任何未平仓交易都应被映射。
            # 这个逻辑很复杂，取决于期望的行为（例如，是否应该尝试通过魔术数字和交易品种查找交易？）。
            # 目前，我们将记录主账户状态并关注新交易。
            
            master_positions = state.get('positions', [])
            master_orders = state.get('orders', [])

            logger.info(f"主账户状态: {len(master_positions)} 个未平仓头寸, {len(master_orders)} 个挂单。")
            # 在实际的高级场景中，您将在此处实现逻辑
            # 以将这些主交易与跟单账户上的交易进行匹配，从而
            # 重新填充 self.position_map 和 self.pending_order_map。
            # 例如:
            # for master_pos in master_positions:
            #     for follower in self.config_manager.get_enabled_follower_accounts():
            #         find_and_map_follower_position(...)
            
            logger.info("状态同步完成。引擎已准备好处理新事件。")

    def process_event(self, json_payload: str):
        # 处理来自 ZmqListener 的原始事件。它会验证负载并将其分派到相应的处理程序。
        # Args:
        #     json_payload: 从 MQL5 EA 接收到的 JSON 字符串。
        import json as _json
        try:
            raw = _json.loads(json_payload)
            etype = raw.get("event_type")
            
            logger.debug(f"正在处理事件类型: {etype}")

            if etype == "DEAL_ADD":
                event = DealAddEvent(**raw)
                logger.info(f"DEAL_ADD 事件: ticket={event.ticket}, entry={event.entry}, position={event.position_id}")
                self._handle_deal_add(event)

            elif etype in ("ORDER_ADD", "ORDER_UPDATE", "ORDER_DELETE"):
                event = OrderEvent(**raw)
                logger.info(f"{etype} 事件: ticket={event.ticket}, type={event.type}, state={event.state}")
                
                if etype == "ORDER_ADD":
                    self._handle_order_add(event)
                elif etype == "ORDER_UPDATE":
                    self._handle_order_update(event)
                elif etype == "ORDER_DELETE":
                    self._handle_order_delete(event)

            elif etype == "POSITION_MODIFY":
                event = PositionModifyEvent(**raw)
                logger.info(f"POSITION_MODIFY 事件: ticket={event.ticket}, sl={event.sl}, tp={event.tp}")
                self._handle_position_modify(event)

            else:
                logger.warning(f"未知事件类型 '{etype}'，正在忽略。")

        except Exception as e:
            logger.error(f"TradeEngine 中发生意外错误: {e}", exc_info=True)

    def _handle_deal_add(self, event: DealAddEvent):
        # 处理添加新交易时的逻辑。
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

    def _handle_order_add(self, event: OrderEvent):
        # 处理 ORDER_ADD 事件 - 新订单（市价单或挂单）。
        # 对于状态为 "STARTED" 的市价单，我们通常等待 DEAL_ADD 事件。
        # 对于挂单，我们需要创建相应的挂单。
        if event.state == "PLACED" and event.price_open > 0:
            # 这是一个挂单
            self._handle_new_pending_order(event)
        # 状态为 "STARTED" 的市价单将由 DEAL_ADD 处理

    def _handle_order_update(self, event: OrderEvent):
        # 处理 ORDER_UPDATE 事件 - 修改现有订单。
        if event.state == "PLACED" and event.price_open > 0:
            # 挂单修改
            self._handle_modify_pending_order(event)

    def _handle_order_delete(self, event: OrderEvent):
        # 处理 ORDER_DELETE 事件 - 订单取消。
        self._handle_delete_pending_order(event)

    def _handle_position_modify(self, event: PositionModifyEvent):
        # 处理 POSITION_MODIFY 事件 - SL/TP 修改。
        self._handle_modify_position(event)

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
            for name, result in results.items():
                if result and result.get("status") == "success":
                    follower_result = result["result"]
                    # 滑点检查
                    config = self.config_manager.get_follower_config(name)
                    max_slippage = config.get("max_slippage_pips", 3)
                    price_diff = abs(follower_result.price - event.price)
                    
                    # 此滑点检查已简化。实际需要考虑点/跳。
                    # if price_diff > (max_slippage * point_size):
                    #    logger.warning(f"跟单账户 {name} 的滑点超出限制！")
                    #    # 在此处决定如何处理 - 也许平仓？
                    
                    # 更新映射并保存状态
                    self.position_map[str(event.position_id)] = self.position_map.get(str(event.position_id), {})
                    self.position_map[str(event.position_id)][name] = follower_result.order
                    self._save_state_to_disk()
                    logger.info(f"为 {name} 成功开仓 {follower_result.order} 并保存状态。")
                else:
                    logger.error(f"为 {name} 开仓失败: {result}")

    def _close_positions(self, event: DealAddEvent):
        # 处理跟单账户的平仓。
        # Args:
        #     event: DealAddEvent (或包含 position_id 的任何事件)
        with self.lock:
            master_position_id = str(event.position_id)
            follower_positions = self.position_map.pop(master_position_id, {})

            if not follower_positions:
                logger.info(f"未找到主仓位 {master_position_id} 的跟单仓位进行平仓。")
                return

            trade_requests = self._build_trade_requests(event, is_open=False, follower_positions=follower_positions)
            if not trade_requests:
                logger.info("未生成平仓交易请求。")
                return

            results = self.account_manager.execute_trades_parallel(trade_requests)

            # 处理结果并从映射中移除已平仓位
            for name, result in results.items():
                if result and result.get("status") == "success":
                    logger.info(f"为 {name} 成功平仓。")
                else:
                    logger.error(f"为 {name} 平仓失败: {result}")
            
            self._save_state_to_disk()
            logger.info(f"已为所有跟单账户平仓主仓位 {master_position_id} 并保存状态。")

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
            master_order_id = str(event.ticket)
            follower_orders = self.pending_order_map.get(master_order_id, {})

            if not follower_orders:
                logger.info(f"未找到主订单 {master_order_id} 的跟单挂单进行修改。")
                return
            
            trade_requests = self._build_pending_order_requests(event, "MODIFY", follower_orders)
            if not trade_requests:
                logger.info("未生成修改挂单请求。")
                return

            results = self.account_manager.execute_trades_parallel(trade_requests)

            for name, result in results.items():
                if result and result.get("status") == "success":
                    logger.info(f"为 {name} 成功修改挂单。")
                else:
                    logger.error(f"为 {name} 修改挂单失败: {result}")
            
            self._save_state_to_disk()
            logger.info(f"已为所有跟单账户修改挂单 {master_order_id} 并保存状态。")


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

    def _handle_modify_position(self, event: PositionModifyEvent):
        # 处理修改现有头寸（例如 SL/TP）的事件。
        with self.lock:
            master_position_id = str(event.ticket)
            follower_positions = self.position_map.get(master_position_id, {})

            if not follower_positions:
                logger.info(f"未找到主仓位 {master_position_id} 的跟单仓位进行修改。")
                return

            trade_requests = self._build_trade_requests(event, is_open=False, is_modify=True, follower_positions=follower_positions)
            if not trade_requests:
                logger.info("未生成修改头寸请求。")
                return

            results = self.account_manager.execute_trades_parallel(trade_requests)

            for name, result in results.items():
                if result and result.get("status") == "success":
                    logger.info(f"为 {name} 成功修改头寸。")
                else:
                    logger.error(f"为 {name} 修改头寸失败: {result}")
            
            self._save_state_to_disk()
            logger.info(f"已为所有跟单账户修改头寸 {master_position_id} 并保存状态。")

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
        master_symbol_info = mt5.symbol_info(event.symbol)
        if master_symbol_info is None:
            logger.error(f"无法获取交易品种 {event.symbol} 的信息。")
            return {}
        master_point = master_symbol_info.point

        for follower_name, config in self.config_manager.get_enabled_follower_accounts().items():
            try:
                # 获取跟单账户的交易品种映射
                symbol = config.get("symbol_mapping", {}).get(event.symbol, event.symbol)
                follower_symbol_info = mt5.symbol_info(symbol)
                if follower_symbol_info is None:
                    logger.warning(f"跟单账户 {follower_name}: 无法获取交易品种 {symbol} 的信息。跳过此交易。")
                    continue
                follower_point = follower_symbol_info.point

                # 计算跟单手数
                if config.get("risk_mode") == "percentage":
                    # 基于风险百分比计算手数
                    account_info = self.account_manager.get_account_info(follower_name)
                    if not account_info:
                        logger.warning(f"跟单账户 {follower_name}: 无法获取账户信息。跳过此交易。")
                        continue
                    balance = account_info.balance
                    risk_percentage = config.get("risk_percentage", 0.01) # 默认 1%
                    
                    # 假设 1% 风险，止损点为 master_sl。这需要更复杂的计算。
                    # 这只是一个占位符逻辑。实际的风险管理涉及更多因素。
                    if event.sl > 0 and event.price > 0:
                        risk_amount = balance * risk_percentage
                        # 简化：使用主账户的点差和点值
                        price_diff = abs(event.price - event.sl)
                        if price_diff == 0: # 避免除以零
                            logger.warning(f"跟单账户 {follower_name}: 止损价格与开仓价格相同，无法计算风险手数。")
                            continue
                        
                        # 粗略计算每手的风险金额 (点值 * 止损点差)
                        # 这里的点值计算需要精确地针对每个交易品种
                        # 对于大多数货币对，1 手 = 100,000 单位，1 个点 = 10 美元 (对于 JPY 对是 1000)
                        # 这是一个非常简化的例子，需要根据实际交易品种和账户货币调整
                        tick_size = follower_symbol_info.tick_size
                        tick_value = follower_symbol_info.tick_value

                        # 计算每手亏损的金额 (在跟单账户的货币)
                        # 如果 symbol_info.trade_tick_value_profit 是基于手数计算的，那会更有用
                        # 当前我们假设简单的 10 美元/手/点模型 (需要修正)
                        
                        # 获取交易品种的每点价值（例如，对于 EURUSD，1标准手每点价值10美元）
                        # mt5.symbol_info_tick(symbol).point * mt5.symbol_info(symbol).trade_tick_value
                        # 简化处理：假设每点价值是固定的，这需要根据实际情况调整
                        points_risked = abs(event.price - event.sl) / master_point

                        if points_risked == 0:
                            lot_size = config.get("fixed_lot_size", 0.01) # 如果无法计算，则使用固定手数
                            logger.warning(f"跟单账户 {follower_name}: 风险点数为零，使用固定手数 {lot_size}。")
                        else:
                            # 这是一个非常简化的手数计算，需要考虑交易品种、账户货币、杠杆等。
                            # 理想情况下，您应该使用 MT5 的订单核算功能。
                            # 假设每标准手每点价值 10 美元（对于货币对）
                            approx_value_per_point_per_lot = 10 # 这需要根据交易品种动态确定
                            risk_per_lot = points_risked * approx_value_per_point_per_lot

                            if risk_per_lot > 0:
                                lot_size = max(follower_symbol_info.volume_min, min(risk_amount / risk_per_lot, follower_symbol_info.volume_max))
                                lot_size = self.account_manager.normalize_volume(follower_name, symbol, lot_size)
                            else:
                                lot_size = config.get("fixed_lot_size", 0.01)
                                logger.warning(f"跟单账户 {follower_name}: 每手风险为零，使用固定手数 {lot_size}。")

                        logger.info(f"跟单账户 {follower_name}: 基于风险 {risk_percentage*100}% 计算的手数为 {lot_size}。")
                    else:
                        lot_size = config.get("fixed_lot_size", 0.01) # 如果没有止损，则使用固定手数
                        logger.warning(f"跟单账户 {follower_name}: 无止损，使用固定手数 {lot_size}。")
                else: # 固定手数
                    lot_size = config.get("fixed_lot_size", 0.01)
                    logger.info(f"跟单账户 {follower_name}: 使用固定手数 {lot_size}。")

                # 确保手数在有效范围内
                lot_size = max(follower_symbol_info.volume_min, min(lot_size, follower_symbol_info.volume_max))
                # 调整手数以符合步进大小
                lot_size = round(lot_size / follower_symbol_info.volume_step) * follower_symbol_info.volume_step
                
                if lot_size <= 0:
                    logger.warning(f"跟单账户 {follower_name}: 计算出的手数为 {lot_size}，无效。跳过此交易。")
                    continue

                trade_type = event.type
                price = event.price
                sl = event.sl
                tp = event.tp
                comment = f"Copied from master {event.magic}"

                # 应用反向交易策略
                if config.get("reverse_trades", False):
                    trade_type = self.reverse_order_type_map.get(trade_type, trade_type)
                    logger.info(f"跟单账户 {follower_name}: 应用反向交易策略。新类型: {trade_type}")
                    # 反转 SL/TP (如果适用且有意义)
                    if sl > 0 and tp > 0:
                        # 这需要更复杂的逻辑来确定新的 SL/TP，因为它们现在相对于反转后的开仓价格。
                        # 暂时我们只记录。
                        logger.warning("反转交易的 SL/TP 逻辑尚未实现。")
                        sl = 0 # 暂时禁用，直到实现正确逻辑
                        tp = 0 # 暂时禁用，直到实现正确逻辑

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": lot_size,
                    "type": self.order_type_to_mt5.get(trade_type, mt5.ORDER_TYPE_BUY), # 默认 BUY
                    "price": price,
                    "deviation": int(config.get("max_slippage_pips", 3) / follower_point), # 将点差转换为 MT5 偏差
                    "sl": sl,
                    "tp": tp,
                    "comment": comment,
                    "type_time": mt5.ORDER_TIME_GTC, # Good Till Cancel
                    "type_filling": mt5.ORDER_FILL_FOK, # Fill Or Kill
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
                            follower_pos_info = follower_pos_info[0] # positions_get 返回元组
                            # 平仓操作使用相反的类型
                            close_type = mt5.ORDER_TYPE_SELL if follower_pos_info.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                            request = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": symbol,
                                "volume": follower_pos_info.volume,
                                "type": close_type,
                                "position": follower_position_id,
                                "price": mt5.symbol_info_tick(symbol).bid if close_type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask,
                                "deviation": int(config.get("max_slippage_pips", 3) / follower_point),
                                "comment": "Close copied position",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling": mt5.ORDER_FILL_FOK,
                                "magic": self.config_manager.EA_MAGIC,
                            }
                            logger.debug(f"为 {follower_name} 构建平仓请求: {request}")
                            trade_requests[follower_name] = request
                        else:
                            logger.warning(f"跟单账户 {follower_name}: 无法获取跟单仓位 {follower_position_id} 的信息。跳过平仓。")
                    else:
                        logger.warning(f"跟单账户 {follower_name}: 未找到要平仓的跟单仓位。跳过。")
            except Exception as e:
                logger.error(f"为跟单账户 {follower_name} 构建交易请求失败: {e}", exc_info=True)
                continue

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
        master_symbol_info = mt5.symbol_info(event.symbol)
        if master_symbol_info is None:
            logger.error(f"无法获取交易品种 {event.symbol} 的信息。")
            return {}
        master_point = master_symbol_info.point

        for follower_name, config in self.config_manager.get_enabled_follower_accounts().items():
            try:
                symbol = config.get("symbol_mapping", {}).get(event.symbol, event.symbol)
                follower_symbol_info = mt5.symbol_info(symbol)
                if follower_symbol_info is None:
                    logger.warning(f"跟单账户 {follower_name}: 无法获取交易品种 {symbol} 的信息。跳过此订单。")
                    continue
                follower_point = follower_symbol_info.point

                # 跟单手数计算与开仓逻辑类似，但需针对挂单场景调整
                if config.get("risk_mode") == "percentage":
                    # 挂单的风险计算更复杂，因为它依赖于未来的开仓价格。
                    # 暂时，我们假设在挂单时不计算风险，直接使用固定手数，或者在市价单时应用风险。
                    lot_size = config.get("fixed_lot_size", 0.01)
                    logger.warning(f"跟单账户 {follower_name}: 挂单不支持风险百分比模式，使用固定手数 {lot_size}。")
                else: # 固定手数
                    lot_size = config.get("fixed_lot_size", 0.01)

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
                comment = f"Copied pending order from master {event.magic}"

                # 应用反向交易策略 (针对挂单类型)
                if config.get("reverse_trades", False):
                    order_type = self.reverse_order_type_map.get(order_type, order_type)
                    logger.info(f"跟单账户 {follower_name}: 应用反向交易策略。新类型: {order_type}")
                    # 反转 SL/TP (需要更复杂的逻辑)
                    sl = 0 # 暂时禁用
                    tp = 0 # 暂时禁用

                request = {
                    "action": mt5.TRADE_ACTION_PENDING,
                    "symbol": symbol,
                    "volume": lot_size,
                    "type": self.order_type_to_mt5.get(order_type, mt5.ORDER_TYPE_BUY_LIMIT), # 默认 BUY_LIMIT
                    "price": price_open,
                    "deviation": int(config.get("max_slippage_pips", 3) / follower_point),
                    "sl": sl,
                    "tp": tp,
                    "comment": comment,
                    "type_time": mt5.ORDER_TIME_GTC, 
                    "type_filling": mt5.ORDER_FILL_FOK, 
                    "magic": self.config_manager.EA_MAGIC,
                }
                
                if action == "ADD":
                    logger.debug(f"为 {follower_name} 构建新挂单请求: {request}")
                    order_requests[follower_name] = request
                elif action == "MODIFY":
                    follower_order_ticket = follower_orders.get(follower_name)
                    if follower_order_ticket:
                        request["action"] = mt5.TRADE_ACTION_MODIFY # 修改订单动作
                        request["order"] = follower_order_ticket
                        # 对于修改，我们只需要 price, sl, tp, expiration
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
                            "comment": "Remove copied pending order",
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