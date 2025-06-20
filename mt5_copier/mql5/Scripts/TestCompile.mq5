//+------------------------------------------------------------------+
//|                                                TestCompile.mq5   |
//|                                      MT5 Trade Copier System     |
//|                                 Test script for compilation      |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "1.0"
#property script_show_inputs

// 测试包含所有必要的头文件
#include <Zmq/Zmq.mqh>
#include <../Include/ZmqConfig.mqh>
#include <../Include/TradeEventSerializer.mqh>
#include <../Include/ProfessionalJSON.mqh>

//+------------------------------------------------------------------+
//| Script program start function                                    |
//+------------------------------------------------------------------+
void OnStart()
{
    Print("=== MT5 Trade Copier Compilation Test ===");
    
    // 测试ZMQ组件
    Print("Testing ZMQ components...");
    ZmqContext* context = new ZmqContext();
    if(context != NULL)
    {
        Print("✓ ZmqContext created successfully");
        
        // 测试Socket创建
        ZmqSocket* socket = new ZmqSocket(context, ZMQ_REQ);
        if(socket != NULL)
        {
            Print("✓ ZmqSocket created successfully");
            delete socket;
        }
        
        delete context;
    }
    
    // 测试JSON序列化器
    Print("\nTesting JSON serializer...");
    CProfessionalJSON* json = new CProfessionalJSON();
    if(json != NULL)
    {
        json.StartObject();
        json.Add("test", "value");
        json.Add("number", (long)123);
        json.Add("float", (double)1.23456, 5);
        json.EndObject();
        
        string result = json.ToString();
        Print("✓ JSON output: ", result);
        
        delete json;
    }
    
    // 测试交易事件序列化器
    Print("\nTesting Trade Event Serializer...");
    CTradeEventSerializer* serializer = new CTradeEventSerializer();
    if(serializer != NULL)
    {
        string heartbeat = serializer.SerializeHeartbeat();
        Print("✓ Heartbeat JSON: ", heartbeat);
        
        delete serializer;
    }
    
    // 测试ZMQ版本
    Print("\nZMQ Library Version: ", Zmq::getVersion());
    
    Print("\n=== All components compiled successfully! ===");
} 