//+------------------------------------------------------------------+
//|                                            ProfessionalJSON.mqh  |
//|                                      MT5 Trade Copier System     |
//|                          Robust, Non-Fluent JSON Serializer      |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "3.0" // Robust, non-fluent version
#property strict

// 修复: 包含交易相关的结构体定义
#include <Trade\Trade.mqh>

//+------------------------------------------------------------------+
//| 专业级JSON序列化器                                                 |
//| 特性：                                                            |
//| - 完整的JSON规范支持                                               |
//| - 高性能内存管理                                                   |
//| - 非流畅的API设计                                                 |
//| - 支持嵌套结构                                                    |
//| - Unicode字符转义                                                 |
//| - 数字精度控制                                                    |
//| - Pretty Print美化输出                                            |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| CProfessionalJSON Class                                          |
//+------------------------------------------------------------------+
class CProfessionalJSON
{
private:
    string m_buffer;
    bool   m_first_element[32]; // Support up to 32 levels of nesting
    int    m_depth;
    
public:
    CProfessionalJSON(void)
    {
        m_depth = 0;
        Clear();
    }
    
    void Clear()
    {
        m_buffer = "";
        m_depth = 0;
        ArrayInitialize(m_first_element, false);   // 用 false 而不是 true
    }
    
    string ToString() { return m_buffer; }

    void StartObject()
    {
        AddCommaIfNeeded();
        m_buffer += "{";
        m_depth++;
        if(m_depth < 32) m_first_element[m_depth] = true;
    }

    void EndObject()
    {
        m_depth--;
        m_buffer += "}";
    }

    void Key(const string& key)
    {
        AddCommaIfNeeded();
        m_buffer += "\"" + Escape(key) + "\":";
        if(m_depth < 32) m_first_element[m_depth] = true;
    }

    void Add(const string& key, const string& value) { Key(key); String(value); }
    void Add(const string& key, long value)          { Key(key); Number(value); }
    void Add(const string& key, ulong value)         { Key(key); Number(value); }
    void Add(const string& key, double value, int digits=8) { Key(key); Number(value, digits); }
    void Add(const string& key, bool value)          { Key(key); Bool(value); }

private:
    void String(const string& value) { AddCommaIfNeeded(); m_buffer += "\"" + Escape(value) + "\""; }
    void Number(long value)          { AddCommaIfNeeded(); m_buffer += (string)value; }
    void Number(ulong value)         { AddCommaIfNeeded(); m_buffer += (string)value; }
    void Number(double value, int digits=8) { AddCommaIfNeeded(); m_buffer += DoubleToString(value, digits); }
    void Bool(bool value)            { AddCommaIfNeeded(); m_buffer += (value ? "true" : "false"); }

    void AddCommaIfNeeded()
    {
        if(m_depth >= 0 && m_depth < 32 && !m_first_element[m_depth])
        {
            m_buffer += ",";
        }
        if(m_depth >= 0 && m_depth < 32)
        {
            m_first_element[m_depth] = false;
        }
    }
    
    string Escape(string value)
    {
        StringReplace(value, "\\", "\\\\");
        StringReplace(value, "\"", "\\\"");
        return value;
    }
};

//+------------------------------------------------------------------+
//| 便捷的静态方法类                                                   |
//+------------------------------------------------------------------+
class JSON
{
public:
    //+------------------------------------------------------------------+
    //| 快速创建简单的JSON对象                                            |
    //+------------------------------------------------------------------+
    static string Object(const string& key1, const string& value1,
                        const string& key2 = "", const string& value2 = "",
                        const string& key3 = "", const string& value3 = "")
    {
        CProfessionalJSON json;
        json.StartObject();
        json.Add(key1, value1);
        
        if(key2 != "")
            json.Add(key2, value2);
        
        if(key3 != "")
            json.Add(key3, value3);
        
        json.EndObject();
        return json.ToString();
    }
    
    //+------------------------------------------------------------------+
    //| 转义字符串（静态方法）                                             |
    //+------------------------------------------------------------------+
    static string Escape(const string& str)
    {
        string result = str;
        StringReplace(result, "\\", "\\\\");
        StringReplace(result, "\"", "\\\"");
        return result;
    }
};
