//+------------------------------------------------------------------+
//|                                                    ZmqConfig.mqh |
//|                                      MT5 Trade Copier System     |
//|                                         ZeroMQ Configuration     |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "1.00"

// ZeroMQ通信端点配置
#define ZMQ_SYNC_URI    "ipc://mt5_sync.ipc"        // 同步握手通道
#define ZMQ_BUS_URI     "ipc://mt5_trade_bus.ipc"   // 事件发布通道

// 通信超时设置
#define ZMQ_SYNC_TIMEOUT    5000    // 握手超时时间(毫秒)
#define ZMQ_SEND_TIMEOUT    1000    // 发送超时时间(毫秒)

// 消息协议定义
#define MSG_SYNC_REQUEST    "READY?"
#define MSG_SYNC_RESPONSE   "ACK"
#define MSG_HEARTBEAT       "HEARTBEAT"

// 事件类型定义
#define EVENT_DEAL_ADD          "TRADE_TRANSACTION_DEAL_ADD"
#define EVENT_ORDER_ADD         "TRADE_TRANSACTION_ORDER_ADD"
#define EVENT_ORDER_DELETE      "TRADE_TRANSACTION_ORDER_DELETE"
#define EVENT_ORDER_UPDATE      "TRADE_TRANSACTION_ORDER_UPDATE"
#define EVENT_POSITION_UPDATE   "TRADE_TRANSACTION_POSITION"

// JSON字段名定义
#define JSON_EVENT_TYPE     "event_type"
#define JSON_ORDER_ID       "order_id"
#define JSON_POSITION_ID    "position_id"
#define JSON_SYMBOL         "symbol"
#define JSON_ACTION         "action"
#define JSON_VOLUME         "volume"
#define JSON_PRICE          "price"
#define JSON_SL             "sl"
#define JSON_TP             "tp"
#define JSON_MAGIC          "magic"
#define JSON_COMMENT        "comment"
#define JSON_TIMESTAMP      "timestamp_msc"

// 调试开关
#define DEBUG_MODE          true
#define LOG_PREFIX          "[TradeCopier EA] " 