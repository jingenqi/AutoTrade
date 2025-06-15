//+------------------------------------------------------------------+
//|                                          TradeEventSerializer.mqh |
//|                                      MT5 Trade Copier System     |
//|                                    Trade Event JSON Serializer   |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "1.00"

#include "ZmqConfig.mqh"
#include "ProfessionalJSON.mqh"  // 使用专业级JSON构建器

//+------------------------------------------------------------------+
//| 交易事件序列化器类                                                  |
//+------------------------------------------------------------------+
class CTradeEventSerializer
{
public:
    //+------------------------------------------------------------------+
    //| 构造函数                                                          |
    //+------------------------------------------------------------------+
    CTradeEventSerializer() {}
    
    //+------------------------------------------------------------------+
    //| 析构函数                                                          |
    //+------------------------------------------------------------------+
    ~CTradeEventSerializer() {}
    
    //+------------------------------------------------------------------+
    //| 序列化交易事件                                                     |
    //+------------------------------------------------------------------+
    string SerializeTradeEvent(const MqlTradeTransaction& trans, 
                              const MqlTradeRequest& request,
                              const MqlTradeResult& result)
    {
        CProfessionalJSON json; // 使用专业级构建器
        json.StartObject();

        // 事件类型 & 基础字段
        json.Key(JSON_EVENT_TYPE)->String(GetEventType(trans.type));
        json.Key(JSON_ORDER_ID)->Number(trans.order);
        json.Key(JSON_POSITION_ID)->Number(trans.position);
        json.Key(JSON_SYMBOL)->String(trans.symbol);
        json.Key(JSON_TIMESTAMP)->Number(GetMicrosecondCount());

        // 类型相关字段
        if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
        {
            json.Key(JSON_ACTION)->String(GetActionType(trans.deal_type));
            json.Key(JSON_VOLUME)->Number(trans.volume);
            json.Key(JSON_PRICE)->Number(trans.price, 5);
            json.Key(JSON_SL)->Number(trans.price_sl, 5);
            json.Key(JSON_TP)->Number(trans.price_tp, 5);
        }
        else if(trans.type == TRADE_TRANSACTION_ORDER_ADD ||
                trans.type == TRADE_TRANSACTION_ORDER_UPDATE)
        {
            json.Key(JSON_ACTION)->String(GetOrderActionType(trans.order_type));
            json.Key(JSON_VOLUME)->Number(trans.volume);
            json.Key(JSON_PRICE)->Number(trans.price, 5);
            json.Key(JSON_SL)->Number(trans.price_sl, 5);
            json.Key(JSON_TP)->Number(trans.price_tp, 5);
        }
        else if(trans.type == TRADE_TRANSACTION_ORDER_DELETE)
        {
            json.Key(JSON_ACTION)->String("ORDER_DELETE");
        }
        else if(trans.type == TRADE_TRANSACTION_POSITION)
        {
            json.Key(JSON_ACTION)->String("POSITION_UPDATE");
            json.Key(JSON_VOLUME)->Number(trans.volume);
            json.Key(JSON_PRICE)->Number(trans.price, 5);
            json.Key(JSON_SL)->Number(trans.price_sl, 5);
            json.Key(JSON_TP)->Number(trans.price_tp, 5);
        }

        // 额外信息
        if(request.magic > 0)
            json.Key(JSON_MAGIC)->Number(request.magic);
        if(StringLen(request.comment) > 0)
            json.Key(JSON_COMMENT)->String(request.comment);

        json.EndObject();
        return json.GetString();
    }
    
    //+------------------------------------------------------------------+
    //| 序列化心跳消息                                                     |
    //+------------------------------------------------------------------+
    string SerializeHeartbeat()
    {
        CProfessionalJSON json;
        json.StartObject();
        json.Key("type")->String(MSG_HEARTBEAT);
        json.Key("timestamp")->Number(GetMicrosecondCount());
        json.Key("account")->Number(AccountInfoInteger(ACCOUNT_LOGIN));
        json.EndObject();
        return json.GetString();
    }
    
private:
    //+------------------------------------------------------------------+
    //| 获取事件类型字符串                                                 |
    //+------------------------------------------------------------------+
    string GetEventType(ENUM_TRADE_TRANSACTION_TYPE type)
    {
        switch(type)
        {
            case TRADE_TRANSACTION_DEAL_ADD:      return EVENT_DEAL_ADD;
            case TRADE_TRANSACTION_ORDER_ADD:     return EVENT_ORDER_ADD;
            case TRADE_TRANSACTION_ORDER_DELETE:  return EVENT_ORDER_DELETE;
            case TRADE_TRANSACTION_ORDER_UPDATE:  return EVENT_ORDER_UPDATE;
            case TRADE_TRANSACTION_POSITION:      return EVENT_POSITION_UPDATE;
            default:                              return "UNKNOWN";
        }
    }
    
    //+------------------------------------------------------------------+
    //| 获取交易动作类型                                                   |
    //+------------------------------------------------------------------+
    string GetActionType(ENUM_DEAL_TYPE type)
    {
        switch(type)
        {
            case DEAL_TYPE_BUY:   return "BUY";
            case DEAL_TYPE_SELL:  return "SELL";
            default:              return "UNKNOWN";
        }
    }
    
    //+------------------------------------------------------------------+
    //| 获取订单动作类型                                                   |
    //+------------------------------------------------------------------+
    string GetOrderActionType(ENUM_ORDER_TYPE type)
    {
        switch(type)
        {
            case ORDER_TYPE_BUY:              return "BUY";
            case ORDER_TYPE_SELL:             return "SELL";
            case ORDER_TYPE_BUY_LIMIT:        return "BUY_LIMIT";
            case ORDER_TYPE_SELL_LIMIT:       return "SELL_LIMIT";
            case ORDER_TYPE_BUY_STOP:         return "BUY_STOP";
            case ORDER_TYPE_SELL_STOP:        return "SELL_STOP";
            case ORDER_TYPE_BUY_STOP_LIMIT:   return "BUY_STOP_LIMIT";
            case ORDER_TYPE_SELL_STOP_LIMIT:  return "SELL_STOP_LIMIT";
            default:                          return "UNKNOWN";
        }
    }
}; 