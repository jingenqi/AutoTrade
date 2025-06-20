//+------------------------------------------------------------------+
//|                                                  ZmqConfig.mqh   |
//|                                      MT5 Trade Copier System     |
//|                                 ZMQ Configuration for MQL5       |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "2.0"
#property strict

// --- 通信模式选择 ---
// 取消下面的注释以切换到TCP模式进行跨设备测试。
// 默认情况下，EA使用高性能的IPC模式。
// #define USE_TCP_MODE

// --- 常量定义 ---
#ifdef USE_TCP_MODE
    // TCP 模式配置 (用于跨设备测试)
    // 重要：这里的IP地址必须是运行Python脚本的机器的IP地址。
    #define ZMQ_SYNC_URI       "tcp://127.0.0.1:5555"
    #define ZMQ_BUS_URI        "tcp://127.0.0.1:5556"
#else
    // IPC 模式配置 (用于高性能本地交易)
    // 文件名必须与Python端的settings.py保持一致。
    #define ZMQ_SYNC_URI       "ipc://mt5_sync.ipc"
    #define ZMQ_BUS_URI        "ipc://mt5_trade_bus.ipc"
#endif

#define ZMQ_SYNC_TIMEOUT    10000 // 同步握手超时 (毫秒)

// --- 消息协议 ---
#define MSG_SYNC_REQUEST    "READY?"
#define MSG_SYNC_RESPONSE   "ACK"

// --- 日志和调试 ---
#define LOG_PREFIX          "[TradeCopierMaster]"
#define DEBUG_MODE          true

// 通信超时设置
#define ZMQ_SEND_TIMEOUT    1000    // 发送超时时间(毫秒)

// 消息协议定义
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