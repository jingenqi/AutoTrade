//+------------------------------------------------------------------+
//|                                           TradeCopierMaster.mq5  |
//|                                      MT5 Trade Copier System     |
//|                                         Master Account EA        |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property link      "https://www.mql5.com"
#property version   "1.00"
#property strict

// 包含必要的头文件
#include <Zmq/Zmq.mqh>  // 需要安装ZeroMQ库
#include "../Include/ZmqConfig.mqh"
#include "../Include/TradeEventSerializer.mqh"

// 输入参数
input bool   EnableCopier = true;           // 启用跟单
input int    HeartbeatInterval = 5000;      // 心跳间隔(毫秒)
input string MagicComment = "TradeCopier";  // 订单注释

// 全局变量
Context* context = NULL;        // ZMQ上下文
Socket*  pubSocket = NULL;      // 发布套接字
Socket*  reqSocket = NULL;      // 请求套接字
CTradeEventSerializer* serializer = NULL;  // 事件序列化器

bool isConnected = false;       // 连接状态
datetime lastHeartbeat = 0;     // 最后心跳时间

//+------------------------------------------------------------------+
//| Expert initialization function                                    |
//+------------------------------------------------------------------+
int OnInit()
{
    if(!EnableCopier)
    {
        Print(LOG_PREFIX, "Trade copier is disabled");
        return(INIT_SUCCEEDED);
    }
    
    // 创建ZMQ上下文
    context = new Context();
    if(context == NULL)
    {
        Print(LOG_PREFIX, "Failed to create ZMQ context");
        return(INIT_FAILED);
    }
    
    // 创建请求套接字用于同步握手
    reqSocket = new Socket(context, ZMQ_REQ);
    if(reqSocket == NULL)
    {
        Print(LOG_PREFIX, "Failed to create REQ socket");
        return(INIT_FAILED);
    }
    
    // 创建发布套接字用于事件广播
    pubSocket = new Socket(context, ZMQ_PUB);
    if(pubSocket == NULL)
    {
        Print(LOG_PREFIX, "Failed to create PUB socket");
        return(INIT_FAILED);
    }
    
    // 创建序列化器
    serializer = new CTradeEventSerializer();
    
    // 初始化连接
    if(!InitializeConnection())
    {
        Print(LOG_PREFIX, "Failed to initialize connection");
        return(INIT_FAILED);
    }
    
    // 设置定时器用于心跳
    EventSetTimer(HeartbeatInterval / 1000);
    
    Print(LOG_PREFIX, "EA initialized successfully");
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    // 停止定时器
    EventKillTimer();
    
    // 清理资源
    if(serializer != NULL)
    {
        delete serializer;
        serializer = NULL;
    }
    
    if(pubSocket != NULL)
    {
        pubSocket.close();
        delete pubSocket;
        pubSocket = NULL;
    }
    
    if(reqSocket != NULL)
    {
        reqSocket.close();
        delete reqSocket;
        reqSocket = NULL;
    }
    
    if(context != NULL)
    {
        context.term();
        delete context;
        context = NULL;
    }
    
    Print(LOG_PREFIX, "EA deinitialized");
}

//+------------------------------------------------------------------+
//| 初始化连接和同步握手                                                |
//+------------------------------------------------------------------+
bool InitializeConnection()
{
    // 连接同步套接字
    if(!reqSocket.connect(ZMQ_SYNC_URI))
    {
        Print(LOG_PREFIX, "Failed to connect REQ socket to ", ZMQ_SYNC_URI);
        return false;
    }
    
    // 绑定发布套接字
    if(!pubSocket.bind(ZMQ_BUS_URI))
    {
        Print(LOG_PREFIX, "Failed to bind PUB socket to ", ZMQ_BUS_URI);
        return false;
    }
    
    // 执行同步握手
    Print(LOG_PREFIX, "Performing synchronization handshake...");
    
    // 发送同步请求
    ZmqMsg request(MSG_SYNC_REQUEST);
    if(!reqSocket.send(request))
    {
        Print(LOG_PREFIX, "Failed to send sync request");
        return false;
    }
    
    // 等待响应
    ZmqMsg response;
    reqSocket.setsockopt(ZMQ_RCVTIMEO, ZMQ_SYNC_TIMEOUT);
    
    if(!reqSocket.recv(response))
    {
        Print(LOG_PREFIX, "Failed to receive sync response");
        return false;
    }
    
    // 验证响应
    string reply = response.getData();
    if(reply != MSG_SYNC_RESPONSE)
    {
        Print(LOG_PREFIX, "Invalid sync response: ", reply);
        return false;
    }
    
    isConnected = true;
    Print(LOG_PREFIX, "Synchronization successful, connection established");
    return true;
}

//+------------------------------------------------------------------+
//| Trade Transaction event                                           |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                       const MqlTradeRequest& request,
                       const MqlTradeResult& result)
{
    if(!EnableCopier || !isConnected)
        return;
    
    // 过滤需要处理的事件类型
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD &&
       trans.type != TRADE_TRANSACTION_ORDER_ADD &&
       trans.type != TRADE_TRANSACTION_ORDER_DELETE &&
       trans.type != TRADE_TRANSACTION_ORDER_UPDATE &&
       trans.type != TRADE_TRANSACTION_POSITION)
    {
        return;
    }
    
    // 序列化交易事件
    string jsonEvent = serializer->SerializeTradeEvent(trans, request, result);
    
    if(DEBUG_MODE)
    {
        Print(LOG_PREFIX, "Broadcasting event: ", jsonEvent);
    }
    
    // 发送事件
    ZmqMsg message(jsonEvent);
    if(!pubSocket.send(message, ZMQ_DONTWAIT))
    {
        Print(LOG_PREFIX, "Failed to send trade event");
    }
}

//+------------------------------------------------------------------+
//| Timer function                                                    |
//+------------------------------------------------------------------+
void OnTimer()
{
    if(!EnableCopier || !isConnected)
        return;
    
    // 发送心跳
    string heartbeat = serializer->SerializeHeartbeat();
    ZmqMsg message(heartbeat);
    
    if(!pubSocket.send(message, ZMQ_DONTWAIT))
    {
        Print(LOG_PREFIX, "Failed to send heartbeat");
    }
    else if(DEBUG_MODE)
    {
        Print(LOG_PREFIX, "Heartbeat sent");
    }
    
    lastHeartbeat = TimeCurrent();
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
    // EA不需要在每个tick执行操作
    // 所有操作都在事件驱动的回调中处理
} 