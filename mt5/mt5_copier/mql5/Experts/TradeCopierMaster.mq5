//+------------------------------------------------------------------+
//|                                           TradeCopierMaster.mq5 |
//|                      Copyright 2025, E. Jing                    |
//|                                                                 |
//+------------------------------------------------------------------+
#property copyright "Copyright 2025, E. Jing"
#property link      "事件驱动交易"
#property version   "2.00"
#property description "使用 ZeroMQ 发布 MT5 交易事件。"
#property strict

//+------------------------------------------------------------------+
//| ZMQ 函数导入                                                     |
//| 重要：DLL 必须放置在 MQL5/Libraries 文件夹中                       |
//+------------------------------------------------------------------+
#import "zmq.dll"
  long zmq_ctx_new();
  long zmq_socket(long context, int type);
  int  zmq_bind(long socket, uchar &endpoint[]);
  int  zmq_connect(long socket, uchar &endpoint[]);
  int  zmq_close(long socket);
  int  zmq_ctx_term(long context);
  int  zmq_send(long socket, uchar &data[], int size, int flags);
  int  zmq_recv(long socket, uchar &data[], int size, int flags);
  int  zmq_setsockopt(long socket, int option, const uchar &optval[], int optvallen);
#import

//--- ZMQ 常量
#define ZMQ_REP                               4
#define ZMQ_PUB                               1
#define ZMQ_SNDMORE                           2
#define ZMQ_DONTWAIT                          1

//--- 全局句柄
long g_zmq_context = -1;
long g_pub_socket  = -1;
long g_rep_socket  = -1;

//--- 输入参数
input string InpRepEndpoint   = "tcp://*:5555"; // 用于同步的 REP 套接字
input string InpPubEndpoint   = "tcp://*:5556"; // 用于事件的总线 PUB 套接字
//input string InpRepEndpoint   = "ipc://\\\\.\\pipe\\mt5_sync.ipc"; // 用于同步的 REP 套接字
//input string InpPubEndpoint   = "ipc://\\\\.\\pipe\\mt5_trade.ipc"; // 用于事件的 PUB 套接字
input string InpTopic         = "TRADE_EVENT";  // ZMQ 交易事件主题

//--- 同步标志
bool g_is_synced = false;

//--- 帮助函数：将字符串转换为 uchar 数组
void StringToUcharArray(const string &in_str, uchar &out_array[])
{
  int size = StringToCharArray(in_str, out_array, 0, -1, CP_UTF8) - 1;
  if(size > 0)
    ArrayResize(out_array, size);
}

//--- 帮助函数：转义 JSON 特殊字符
string EscapeJsonString(string str)
{
  StringReplace(str, "\\", "\\\\");
  StringReplace(str, "\"", "\\\"");
  return str;
}

//+------------------------------------------------------------------+
//| 枚举到字符串转换函数                                               |
//+------------------------------------------------------------------+
//| 将 ENUM_ORDER_TYPE 转换为字符串。                                  |
//+------------------------------------------------------------------+
string OrderTypeToString(long type)
{
  switch((int)type)
  {
    case ORDER_TYPE_BUY:             return "BUY";
    case ORDER_TYPE_SELL:            return "SELL";
    case ORDER_TYPE_BUY_LIMIT:       return "BUY_LIMIT";
    case ORDER_TYPE_SELL_LIMIT:      return "SELL_LIMIT";
    case ORDER_TYPE_BUY_STOP:        return "BUY_STOP";
    case ORDER_TYPE_SELL_STOP:       return "SELL_STOP";
    case ORDER_TYPE_BUY_STOP_LIMIT:  return "BUY_STOP_LIMIT";
    case ORDER_TYPE_SELL_STOP_LIMIT: return "SELL_STOP_LIMIT";
    case ORDER_TYPE_CLOSE_BY:        return "CLOSE_BY";
    default:                         return "UNKNOWN";
  }
}

//+------------------------------------------------------------------+
//| 将 ENUM_ORDER_STATE 转换为字符串。                                 |
//+------------------------------------------------------------------+
string OrderStateToString(long state)
{
  switch((int)state)
  {
    case ORDER_STATE_STARTED:        return "STARTED";
    case ORDER_STATE_PLACED:         return "PLACED";
    case ORDER_STATE_CANCELED:       return "CANCELED";
    case ORDER_STATE_PARTIAL:        return "PARTIAL";
    case ORDER_STATE_FILLED:         return "FILLED";
    case ORDER_STATE_REJECTED:       return "REJECTED";
    case ORDER_STATE_EXPIRED:        return "EXPIRED";
    case ORDER_STATE_REQUEST_ADD:    return "REQUEST_ADD";
    case ORDER_STATE_REQUEST_MODIFY: return "REQUEST_MODIFY";
    case ORDER_STATE_REQUEST_CANCEL: return "REQUEST_CANCEL";
    default:                         return "UNKNOWN";
  }
}

//+------------------------------------------------------------------+
//| 将 ENUM_DEAL_TYPE 转换为字符串。                                   |
//+------------------------------------------------------------------+
string DealTypeToString(long type)
{
  switch((int)type)
  {
    case DEAL_TYPE_BUY:     return "BUY";
    case DEAL_TYPE_SELL:    return "SELL";
    case DEAL_TYPE_BALANCE: return "BALANCE";
    case DEAL_TYPE_CREDIT:  return "CREDIT";
    case DEAL_TYPE_CHARGE:  return "CHARGE";
    default:                return "UNKNOWN";
  }
}

//+------------------------------------------------------------------+
//| 将 ENUM_DEAL_ENTRY 转换为字符串。                                  |
//+------------------------------------------------------------------+
string DealEntryToString(long entry)
{
  switch((int)entry)
  {
    case DEAL_ENTRY_IN:     return "IN";
    case DEAL_ENTRY_OUT:    return "OUT";
    case DEAL_ENTRY_INOUT:  return "INOUT";
    case DEAL_ENTRY_OUT_BY: return "OUT_BY";
    default:                return "UNKNOWN";
  }
}

//+------------------------------------------------------------------+
//| 将 ENUM_POSITION_TYPE 转换为字符串。                               |
//+------------------------------------------------------------------+
string PositionTypeToString(long type)
{
  switch((int)type)
  {
    case POSITION_TYPE_BUY:  return "BUY";
    case POSITION_TYPE_SELL: return "SELL";
    default:                 return "UNKNOWN";
  }
}

//+------------------------------------------------------------------+
//| 获取所有未平仓头寸和挂单的 JSON 字符串                           |
//+------------------------------------------------------------------+
string GetCurrentStateAsJson()
{
    string positions_json = "\"positions\":[";
    int total_positions = PositionsTotal();
    bool first = true;

    for(int i = 0; i < total_positions; i++)
    {
        if(PositionGetTicket(i))
        {
            if(!first) positions_json += ",";
            
            positions_json += StringFormat("{\"ticket\":%I64u,\"magic\":%d,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f}",
                                           PositionGetInteger(POSITION_TICKET),
                                           (int)PositionGetInteger(POSITION_MAGIC),
                                           EscapeJsonString(PositionGetString(POSITION_SYMBOL)),
                                           PositionTypeToString(PositionGetInteger(POSITION_TYPE)),
                                           PositionGetDouble(POSITION_VOLUME));
            first = false;
        }
    }
    positions_json += "]";

    string orders_json = "\"orders\":[";
    int total_orders = OrdersTotal();
    first = true;

    for(int i = 0; i < total_orders; i++)
    {
        if(OrderGetTicket(i))
        {
            if(!first) orders_json += ",";

            orders_json += StringFormat("{\"ticket\":%I64u,\"magic\":%d,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,\"price_open\":%.5f}",
                                        OrderGetInteger(ORDER_TICKET),
                                        (int)OrderGetInteger(ORDER_MAGIC),
                                        EscapeJsonString(OrderGetString(ORDER_SYMBOL)),
                                        OrderTypeToString(OrderGetInteger(ORDER_TYPE)),
                                        OrderGetDouble(ORDER_VOLUME_CURRENT),
                                        OrderGetDouble(ORDER_PRICE_OPEN));
            first = false;
        }
    }
    orders_json += "]";
    
    return "{" + positions_json + "," + orders_json + "}";
}

//+------------------------------------------------------------------+
//| EA 初始化函数                                                    |
//+------------------------------------------------------------------+
int OnInit()
{
  Print("尝试初始化 TradeCopierMaster EA v2.0...");
    
  //--- 初始化 ZMQ 上下文
  g_zmq_context = zmq_ctx_new();
  if(g_zmq_context <= 0)
    {
    Print("错误: zmq_ctx_new() 失败或返回了无效的上下文。返回值: ", (string)g_zmq_context);
    Print("请确保 libzmq.dll 位于 MQL5/Libraries 文件夹中且兼容 64 位。");
    return(INIT_FAILED);
    }
  Print("ZMQ 上下文创建成功。上下文: ", (string)g_zmq_context);
    
  //--- 创建并绑定 REP 套接字用于同步
  g_rep_socket = zmq_socket(g_zmq_context, ZMQ_REP);
  if(g_rep_socket <= 0)
    {
    Print("错误: 无法创建 REP 套接字。");
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }

  //--- 将端点字符串转换为 uchar 数组进行绑定
  uchar rep_endpoint_bytes[];
  StringToCharArray(InpRepEndpoint, rep_endpoint_bytes, 0, -1, CP_UTF8);
  if(zmq_bind(g_rep_socket, rep_endpoint_bytes) != 0)
    {
    Print("错误: 无法将 REP 套接字绑定到 ", InpRepEndpoint);
    zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }
    
  //--- 创建并绑定 PUB 套接字用于发布事件
  g_pub_socket = zmq_socket(g_zmq_context, ZMQ_PUB);
  if(g_pub_socket <= 0)
    {
    Print("错误: 无法创建 PUB 套接字。");
    zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }
  
  //--- 将端点字符串转换为 uchar 数组进行绑定
  uchar pub_endpoint_bytes[];
  StringToCharArray(InpPubEndpoint, pub_endpoint_bytes, 0, -1, CP_UTF8);
  if(zmq_bind(g_pub_socket, pub_endpoint_bytes) != 0)
  {
    Print("错误: 无法将 PUB 套接字绑定到 ", InpPubEndpoint);
    zmq_close(g_rep_socket);
    zmq_close(g_pub_socket);
    zmq_ctx_term(g_zmq_context);
    return(INIT_FAILED);
  }

  Print("EA 已初始化。等待控制器在 ", InpRepEndpoint, " 上发送 'SYNC' 消息。");
  
  //--- 设置定时器以定期处理同步检查
  EventSetTimer(1); // 每 1 秒检查一次同步消息

  return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EA 去初始化函数                                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
  //--- 终止定时器
  EventKillTimer();

  if(g_zmq_context > 0)
  {
    if(g_pub_socket > 0) zmq_close(g_pub_socket);
    if(g_rep_socket > 0) zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
    Print("ZMQ 上下文已终止。");
  }
  
  Print("EA 已去初始化。原因: ", (string)reason);
}

//+------------------------------------------------------------------+
//| 定时器函数                                                       |
//+------------------------------------------------------------------+
void OnTimer()
{
  //--- 如果已同步，定时器中不执行任何操作。
  if(g_is_synced)
  {
    // 客户端可能已断开连接。我们仍然需要监听新的 SYNC 请求。
    // 因此，我们不再终止定时器。EA 始终准备好进行握手。
  }
  
  //--- 同步握手逻辑 ---
  uchar recv_buffer[256]; // 增加缓冲区大小以适应可能更长的消息，例如 GET_STATE
  
  // 检查消息而不阻塞
  int bytes = zmq_recv(g_rep_socket, recv_buffer, 256, ZMQ_DONTWAIT);
  if(bytes > 0)
  {
    string msg = CharArrayToString(recv_buffer, 0, bytes);
    
    // 处理不同类型的请求
    if(msg == "SYNC")
    {
      Print("接收到 'SYNC' 消息。发送 'ACK'。");
      
      uchar ack_message[];
      StringToUcharArray("ACK", ack_message);
      
      // 发送确认
      if(zmq_send(g_rep_socket, ack_message, ArraySize(ack_message), 0) > 0)
      {
          // 仅在成功发送后设置同步标志
          if(!g_is_synced)
          {
              g_is_synced = true;
              Print("同步完成。事件发布已启用。");
          }
      }
    }
    else if(msg == "GET_STATE")
    {
        Print("接收到 'GET_STATE' 消息。发送当前交易状态。");
        string state_json = GetCurrentStateAsJson();
        uchar state_message[];
        StringToUcharArray(state_json, state_message);
        
        // 发送状态 JSON
        zmq_send(g_rep_socket, state_message, ArraySize(state_message), 0);
        
        // 状态请求也意味着客户端已同步
        if(!g_is_synced)
        {
            g_is_synced = true;
            Print("通过状态请求完成同步。事件发布已启用。");
        }
    }
  }
}

//+------------------------------------------------------------------+
//| 以多部分 ZMQ 消息发布交易事件                                      |
//+------------------------------------------------------------------+
void PublishEvent(string json_payload)
{
  if(!g_is_synced || g_pub_socket < 0) return;

  //--- 将主题和负载转换为 uchar 数组
  uchar topic_data[];
  uchar payload_data[];
  StringToUcharArray(InpTopic, topic_data);
  StringToUcharArray(json_payload, payload_data);

  //--- 作为多部分消息发送
  zmq_send(g_pub_socket, topic_data, ArraySize(topic_data), ZMQ_SNDMORE);
  zmq_send(g_pub_socket, payload_data, ArraySize(payload_data), 0);
  
  //Print("Published event: ", json_payload); // 取消注释用于调试
}

//+------------------------------------------------------------------+
//| 交易事务函数                                                     |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
  //--- 在同步完成之前不处理事务
  if(!g_is_synced)
    return;

  string json_payload = "{";
  string event_type_str = "";
  bool event_found = false;

  switch(trans.type)
  {
    //--- 交易已添加
    case TRADE_TRANSACTION_DEAL_ADD:
      if(HistoryDealSelect(trans.deal))
      {
        event_found = true;
        event_type_str = "DEAL_ADD";
        
        // --- 从源订单获取 SL/TP ---
        double sl = 0.0;
        double tp = 0.0;
        ulong order_ticket = HistoryDealGetInteger(trans.deal, DEAL_ORDER);
        if(HistoryOrderSelect(order_ticket))
         {
          sl = HistoryOrderGetDouble(order_ticket, ORDER_SL);
          tp = HistoryOrderGetDouble(order_ticket, ORDER_TP);
         }

        json_payload += StringFormat("\"event_type\":\"%s\",", event_type_str);
        json_payload += StringFormat("\"ticket\":%I64u,", HistoryDealGetInteger(trans.deal, DEAL_TICKET));
        json_payload += StringFormat("\"order_ticket\":%I64u,", order_ticket);
        json_payload += StringFormat("\"position_id\":%I64u,", HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID));
        json_payload += StringFormat("\"magic\":%d,", (int)HistoryDealGetInteger(trans.deal, DEAL_MAGIC));
        json_payload += StringFormat("\"symbol\":\"%s\",", EscapeJsonString(HistoryDealGetString(trans.deal, DEAL_SYMBOL)));
        json_payload += StringFormat("\"type\":\"%s\",", DealTypeToString((long)HistoryDealGetInteger(trans.deal, DEAL_TYPE)));
        json_payload += StringFormat("\"entry\":\"%s\",", DealEntryToString((long)HistoryDealGetInteger(trans.deal, DEAL_ENTRY)));
        json_payload += StringFormat("\"volume\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_VOLUME));
        json_payload += StringFormat("\"price\":%.5f,", HistoryDealGetDouble(trans.deal, DEAL_PRICE));
        json_payload += StringFormat("\"sl\":%.5f,", sl);
        json_payload += StringFormat("\"tp\":%.5f,", tp);
        json_payload += StringFormat("\"commission\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_COMMISSION));
        json_payload += StringFormat("\"swap\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_SWAP));
        json_payload += StringFormat("\"profit\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_PROFIT));
        json_payload += StringFormat("\"comment\":\"%s\",", EscapeJsonString(HistoryDealGetString(trans.deal, DEAL_COMMENT)));
        json_payload += StringFormat("\"time_msc\":%I64u", HistoryDealGetInteger(trans.deal, DEAL_TIME_MSC));
      }
      break;

    //--- 订单已添加、更新或删除
    case TRADE_TRANSACTION_ORDER_ADD:
    case TRADE_TRANSACTION_ORDER_UPDATE:
    case TRADE_TRANSACTION_ORDER_DELETE:
      if(OrderSelect(trans.order))
      {
        event_found = true;
        if(trans.type == TRADE_TRANSACTION_ORDER_ADD) event_type_str = "ORDER_ADD";
        else if(trans.type == TRADE_TRANSACTION_ORDER_UPDATE) event_type_str = "ORDER_UPDATE";
        else event_type_str = "ORDER_DELETE";

        json_payload += StringFormat("\"event_type\":\"%s\",", event_type_str);
        json_payload += StringFormat("\"ticket\":%I64u,", OrderGetInteger(ORDER_TICKET));
        json_payload += StringFormat("\"magic\":%d,", (int)OrderGetInteger(ORDER_MAGIC));
        json_payload += StringFormat("\"symbol\":\"%s\",", EscapeJsonString(OrderGetString(ORDER_SYMBOL)));
        json_payload += StringFormat("\"type\":\"%s\",", OrderTypeToString(OrderGetInteger(ORDER_TYPE)));
        json_payload += StringFormat("\"state\":\"%s\",", OrderStateToString(OrderGetInteger(ORDER_STATE)));
        json_payload += StringFormat("\"volume_initial\":%.2f,", OrderGetDouble(ORDER_VOLUME_INITIAL));
        json_payload += StringFormat("\"volume_current\":%.2f,", OrderGetDouble(ORDER_VOLUME_CURRENT));
        json_payload += StringFormat("\"price_open\":%.5f,", OrderGetDouble(ORDER_PRICE_OPEN));
        json_payload += StringFormat("\"sl\":%.5f,", OrderGetDouble(ORDER_SL));
        json_payload += StringFormat("\"tp\":%.5f,", OrderGetDouble(ORDER_TP));
        json_payload += StringFormat("\"comment\":\"%s\",", EscapeJsonString(OrderGetString(ORDER_COMMENT)));
        json_payload += StringFormat("\"time_setup_msc\":%I64u,", OrderGetInteger(ORDER_TIME_SETUP_MSC));
        json_payload += StringFormat("\"time_done_msc\":%I64u", OrderGetInteger(ORDER_TIME_DONE_MSC));
      }
      break;

    //--- 头寸已更改（例如，SL/TP 修改）
    case TRADE_TRANSACTION_POSITION:
      if(PositionSelectByTicket(trans.position))
      {
        event_found = true;
        event_type_str = "POSITION_MODIFY";
        json_payload += StringFormat("\"event_type\":\"%s\",", event_type_str);
        json_payload += StringFormat("\"ticket\":%I64u,", PositionGetInteger(POSITION_TICKET));
        json_payload += StringFormat("\"magic\":%d,", (int)PositionGetInteger(POSITION_MAGIC));
        json_payload += StringFormat("\"symbol\":\"%s\",", EscapeJsonString(PositionGetString(POSITION_SYMBOL)));
        json_payload += StringFormat("\"type\":\"%s\",", PositionTypeToString(PositionGetInteger(POSITION_TYPE)));
        json_payload += StringFormat("\"volume\":%.2f,", PositionGetDouble(POSITION_VOLUME));
        json_payload += StringFormat("\"price_open\":%.5f,", PositionGetDouble(POSITION_PRICE_OPEN));
        json_payload += StringFormat("\"sl\":%.5f,", PositionGetDouble(POSITION_SL));
        json_payload += StringFormat("\"tp\":%.5f,", PositionGetDouble(POSITION_TP));
        json_payload += StringFormat("\"price_current\":%.5f,", PositionGetDouble(POSITION_PRICE_CURRENT));
        json_payload += StringFormat("\"profit\":%.2f,", PositionGetDouble(POSITION_PROFIT));
        json_payload += StringFormat("\"comment\":\"%s\",", EscapeJsonString(PositionGetString(POSITION_COMMENT)));
        json_payload += StringFormat("\"time_update_msc\":%I64u", PositionGetInteger(POSITION_TIME_UPDATE_MSC));
      }
      break;
  }

  //--- 如果处理了有效的事务，发布事件
  if(event_found && StringLen(json_payload) > 1)
  {
    json_payload += "}";
    PublishEvent(json_payload);
  }
}

//+------------------------------------------------------------------+ 