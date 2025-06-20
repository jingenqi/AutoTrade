//+------------------------------------------------------------------+
//|                                       TradeEventSerializer.mqh   |
//|                                      MT5 Trade Copier System     |
//|                             Serializes trade events to JSON      |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "4.0" // Final, robust version
#property strict

#include "ProfessionalJSON.mqh"

//+------------------------------------------------------------------+
//| CTradeEventSerializer Class                                      |
//+------------------------------------------------------------------+
class CTradeEventSerializer
{
private:
    CProfessionalJSON* m_json;

public:
    //+------------------------------------------------------------------+
    //| Constructor                                                      |
    //+------------------------------------------------------------------+
    CTradeEventSerializer(void)
    {
        m_json = new CProfessionalJSON();
    }

    //+------------------------------------------------------------------+
    //| Destructor                                                       |
    //+------------------------------------------------------------------+
    ~CTradeEventSerializer(void)
    {
        if(CheckPointer(m_json) == POINTER_DYNAMIC) delete m_json;
    }

    //+------------------------------------------------------------------+
    //| 序列化交易事件                                                     |
    //+------------------------------------------------------------------+
    string SerializeTradeEvent(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result)
    {
        m_json->Clear();
        m_json->StartObject();
        
        // --- 基本信息 ---
        m_json->Add("magic", (long)request.magic);
        m_json->Add("comment", request.comment);
        m_json->Add("timestamp_msc", (long)trans.time_msc);
        
        // --- 核心信息 ---
        m_json->Add("event_type", EnumToString(trans.type));
        m_json->Add("order_id", (long)trans.order);
        m_json->Add("position_id", (long)trans.position);
        m_json->Add("symbol", trans.symbol);
        
        // --- 价格和量 ---
        m_json->Add("price", trans.price, 8);
        m_json->Add("volume", trans.volume, 8);
        
        // --- 止损/止盈 ---
        m_json->Add("sl", trans.price_sl, 8);
        m_json->Add("tp", trans.price_tp, 8);
        
        // --- 订单/成交类型 ---
        string action = "N/A";
        if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
        {
            action = EnumToString((ENUM_DEAL_TYPE)trans.deal_type);
        }
        else if(trans.type == TRADE_TRANSACTION_ORDER_ADD || trans.type == TRADE_TRANSACTION_ORDER_DELETE)
        {
            action = EnumToString((ENUM_ORDER_TYPE)trans.order_type);
        }
        m_json->Add("action", action);

        m_json->EndObject();
        return m_json->ToString();
    }
    
    //+------------------------------------------------------------------+
    //| 序列化心跳事件                                                     |
    //+------------------------------------------------------------------+
    string SerializeHeartbeat()
    {
        m_json->Clear();
        m_json->StartObject();
        
        m_json->Add("type", "HEARTBEAT");
        m_json->Add("account", (long)AccountInfoInteger(ACCOUNT_LOGIN));
        m_json->Add("timestamp", (long)TimeCurrent());
        
        m_json->EndObject();
        return m_json->ToString();
    }
}; 