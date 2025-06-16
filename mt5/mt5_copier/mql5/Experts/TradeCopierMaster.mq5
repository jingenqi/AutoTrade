//+------------------------------------------------------------------+
//|                                           TradeCopierMaster.mq5 |
//|                      Copyright 2025, E. Jing                    |
//|                                                                 |
//+------------------------------------------------------------------+
#property copyright "Copyright 2025, E. Jing"
#property link      "Event-pushed Trading"
#property version   "2.00"
#property description "Publishes MT5 trade events using ZeroMQ."
#property strict

//+------------------------------------------------------------------+
//| ZMQ Function imports                                             |
//| Important: The DLL must be placed in MQL5/Libraries folder       |
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

//--- ZMQ Constants
#define ZMQ_REP                               4
#define ZMQ_PUB                               1
#define ZMQ_SNDMORE                           2
#define ZMQ_DONTWAIT                          1

//--- Global Handles
long g_zmq_context = -1;
long g_pub_socket  = -1;
long g_rep_socket  = -1;

//--- Input parameters
input string InpRepEndpoint   = "tcp://*:5555"; // REP socket for sync
input string InpPubEndpoint   = "tcp://*:5556"; // PUB socket for events
input string InpTopic         = "TRADE_EVENT";  // ZMQ topic for trade events

//--- Synchronization flag
bool g_is_synced = false;

//--- Helper function to convert a string to a uchar array
void StringToUcharArray(const string &in_str, uchar &out_array[])
{
  int size = StringToCharArray(in_str, out_array, 0, -1, CP_UTF8) - 1;
  if(size > 0)
    ArrayResize(out_array, size);
}

//--- Helper function to escape special characters for JSON
string EscapeJsonString(string str)
{
  StringReplace(str, "\\", "\\\\");
  StringReplace(str, "\"", "\\\"");
  return str;
}

//+------------------------------------------------------------------+
//| Enum to String Conversion Functions                              |
//+------------------------------------------------------------------+
//| Converts ENUM_ORDER_TYPE to string.                              |
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
//| Converts ENUM_ORDER_STATE to string.                             |
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
//| Converts ENUM_DEAL_TYPE to string.                               |
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
//| Converts ENUM_DEAL_ENTRY to string.                              |
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
//| Converts ENUM_POSITION_TYPE to string.                           |
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
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
  Print("Attempting to initialize TradeCopierMaster EA v2.0...");
    
  //--- Initialize ZMQ context
  g_zmq_context = zmq_ctx_new();
  if(g_zmq_context <= 0)
    {
    Print("Error: zmq_ctx_new() failed or returned an invalid context. Return value: ", (string)g_zmq_context);
    Print("Please ensure libzmq.dll is in the MQL5/Libraries folder and is 64-bit compatible.");
    return(INIT_FAILED);
    }
  Print("ZMQ context created successfully. Context: ", (string)g_zmq_context);
    
  //--- Create and bind REP socket for synchronization
  g_rep_socket = zmq_socket(g_zmq_context, ZMQ_REP);
  if(g_rep_socket <= 0)
    {
    Print("Error: Could not create REP socket.");
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }

  //--- Convert endpoint string to uchar array for binding
  uchar rep_endpoint_bytes[];
  StringToCharArray(InpRepEndpoint, rep_endpoint_bytes, 0, -1, CP_UTF8);
  if(zmq_bind(g_rep_socket, rep_endpoint_bytes) != 0)
    {
    Print("Error: Could not bind REP socket to ", InpRepEndpoint);
    zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }
    
  //--- Create and bind PUB socket for publishing events
  g_pub_socket = zmq_socket(g_zmq_context, ZMQ_PUB);
  if(g_pub_socket <= 0)
    {
    Print("Error: Could not create PUB socket.");
    zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
        return(INIT_FAILED);
    }
  
  //--- Convert endpoint string to uchar array for binding
  uchar pub_endpoint_bytes[];
  StringToCharArray(InpPubEndpoint, pub_endpoint_bytes, 0, -1, CP_UTF8);
  if(zmq_bind(g_pub_socket, pub_endpoint_bytes) != 0)
  {
    Print("Error: Could not bind PUB socket to ", InpPubEndpoint);
    zmq_close(g_rep_socket);
    zmq_close(g_pub_socket);
    zmq_ctx_term(g_zmq_context);
    return(INIT_FAILED);
  }

  Print("EA Initialized. Waiting for 'SYNC' message from controller on ", InpRepEndpoint);

  //--- Synchronization handshake loop
  uchar recv_buffer[64];
  uchar ack_message[];
  StringToUcharArray("ACK", ack_message);

  while(!IsStopped())
  {
    int bytes = zmq_recv(g_rep_socket, recv_buffer, 64, ZMQ_DONTWAIT);
    if(bytes > 0)
    {
      string msg = CharArrayToString(recv_buffer, 0, bytes);
      if(msg == "SYNC")
      {
        Print("'SYNC' message received. Sending 'ACK'.");
        zmq_send(g_rep_socket, ack_message, ArraySize(ack_message), 0);
        g_is_synced = true;
        Print("Synchronization complete. Event publishing enabled.");
        break; // Exit handshake loop
      }
    }
    Sleep(200); // Sleep to prevent high CPU usage
  }

  if(!g_is_synced)
  {
    Print("Initialization stopped before synchronization was complete.");
    return(INIT_FAILED);
  }
  
  return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
  if(g_zmq_context > 0)
  {
    if(g_pub_socket > 0) zmq_close(g_pub_socket);
    if(g_rep_socket > 0) zmq_close(g_rep_socket);
    zmq_ctx_term(g_zmq_context);
    Print("ZMQ context terminated.");
  }
  
  Print("EA deinitialized. Reason: ", (string)reason);
}

//+------------------------------------------------------------------+
//| Publishes a trade event as a multipart ZMQ message               |
//+------------------------------------------------------------------+
void PublishEvent(string json_payload)
{
  if(!g_is_synced || g_pub_socket < 0) return;

  //--- Convert topic and payload to uchar arrays
  uchar topic_data[];
  uchar payload_data[];
  StringToUcharArray(InpTopic, topic_data);
  StringToUcharArray(json_payload, payload_data);

  //--- Send as multipart message
  zmq_send(g_pub_socket, topic_data, ArraySize(topic_data), ZMQ_SNDMORE);
  zmq_send(g_pub_socket, payload_data, ArraySize(payload_data), 0);
  
  //Print("Published event: ", json_payload); // Uncomment for debugging
}

//+------------------------------------------------------------------+
//| Trade Transaction function                                       |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
  //--- Do not process transactions until synchronization is complete
  if(!g_is_synced)
    return;

  string json_payload = "{";
  string event_type_str = "";
  bool event_found = false;

  switch(trans.type)
  {
    //--- A deal was added
    case TRADE_TRANSACTION_DEAL_ADD:
      if(HistoryDealSelect(trans.deal))
      {
        event_found = true;
        event_type_str = "DEAL_ADD";
        json_payload += StringFormat("\"event_type\":\"%s\",", event_type_str);
        json_payload += StringFormat("\"ticket\":%I64u,", HistoryDealGetInteger(trans.deal, DEAL_TICKET));
        json_payload += StringFormat("\"order_ticket\":%I64u,", HistoryDealGetInteger(trans.deal, DEAL_ORDER));
        json_payload += StringFormat("\"magic\":%d,", (int)HistoryDealGetInteger(trans.deal, DEAL_MAGIC));
        json_payload += StringFormat("\"symbol\":\"%s\",", EscapeJsonString(HistoryDealGetString(trans.deal, DEAL_SYMBOL)));
        json_payload += StringFormat("\"type\":\"%s\",", DealTypeToString((long)HistoryDealGetInteger(trans.deal, DEAL_TYPE)));
        json_payload += StringFormat("\"entry\":\"%s\",", DealEntryToString((long)HistoryDealGetInteger(trans.deal, DEAL_ENTRY)));
        json_payload += StringFormat("\"volume\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_VOLUME));
        json_payload += StringFormat("\"price\":%.5f,", HistoryDealGetDouble(trans.deal, DEAL_PRICE));
        json_payload += StringFormat("\"commission\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_COMMISSION));
        json_payload += StringFormat("\"swap\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_SWAP));
        json_payload += StringFormat("\"profit\":%.2f,", HistoryDealGetDouble(trans.deal, DEAL_PROFIT));
        json_payload += StringFormat("\"comment\":\"%s\",", EscapeJsonString(HistoryDealGetString(trans.deal, DEAL_COMMENT)));
        json_payload += StringFormat("\"time_msc\":%I64u", HistoryDealGetInteger(trans.deal, DEAL_TIME_MSC));
      }
      break;

    //--- An order was added, updated, or deleted
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

    //--- A position was changed (e.g., SL/TP modification)
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

  //--- Publish the event if a valid transaction was processed
  if(event_found && StringLen(json_payload) > 1)
  {
    json_payload += "}";
    PublishEvent(json_payload);
  }
}

//+------------------------------------------------------------------+ 