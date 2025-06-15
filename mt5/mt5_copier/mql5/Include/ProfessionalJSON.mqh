//+------------------------------------------------------------------+
//|                                            ProfessionalJSON.mqh  |
//|                                      MT5 Trade Copier System     |
//|                              Professional JSON Serializer        |
//+------------------------------------------------------------------+
#property copyright "MT5 Trade Copier System"
#property version   "2.00"
#property strict

//+------------------------------------------------------------------+
//| 专业级JSON序列化器                                                 |
//| 特性：                                                            |
//| - 完整的JSON规范支持                                               |
//| - 高性能内存管理                                                   |
//| - 流畅的API设计                                                   |
//| - 支持嵌套结构                                                    |
//| - Unicode字符转义                                                 |
//| - 数字精度控制                                                    |
//| - Pretty Print美化输出                                            |
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//| JSON构建器主类                                                     |
//+------------------------------------------------------------------+
class CProfessionalJSON
{
private:
    // JSON内容缓冲区
    string m_buffer;
    
    // 状态管理
    bool   m_in_object;
    bool   m_in_array;
    int    m_depth;
    bool   m_first_element[];
    
    // 格式化选项
    bool   m_pretty_print;
    string m_indent_string;
    int    m_decimal_places;
    
    // 性能优化：预分配缓冲区大小
    int    m_buffer_capacity;
    
public:
    //+------------------------------------------------------------------+
    //| 构造函数                                                          |
    //+------------------------------------------------------------------+
    CProfessionalJSON(bool pretty_print = false, int decimal_places = 8)
    {
        m_buffer = "";
        m_in_object = false;
        m_in_array = false;
        m_depth = 0;
        m_pretty_print = pretty_print;
        m_indent_string = "  ";
        m_decimal_places = decimal_places;
        m_buffer_capacity = 1024;
        
        ArrayResize(m_first_element, 32);
        ArrayInitialize(m_first_element, true);
    }
    
    //+------------------------------------------------------------------+
    //| 析构函数                                                          |
    //+------------------------------------------------------------------+
    ~CProfessionalJSON()
    {
        Clear();
    }
    
    //+------------------------------------------------------------------+
    //| 清空JSON内容                                                      |
    //+------------------------------------------------------------------+
    void Clear()
    {
        m_buffer = "";
        m_in_object = false;
        m_in_array = false;
        m_depth = 0;
        ArrayInitialize(m_first_element, true);
    }
    
    //+------------------------------------------------------------------+
    //| 开始JSON对象                                                      |
    //+------------------------------------------------------------------+
    CProfessionalJSON* StartObject()
    {
        AddCommaIfNeeded();
        
        m_buffer += "{";
        m_in_object = true;
        m_depth++;
        
        if(m_depth < ArraySize(m_first_element))
            m_first_element[m_depth] = true;
        
        if(m_pretty_print)
            m_buffer += "\n";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 结束JSON对象                                                      |
    //+------------------------------------------------------------------+
    CProfessionalJSON* EndObject()
    {
        if(!m_in_object)
        {
            Print("JSON Error: EndObject called without matching StartObject");
            return GetPointer(this);
        }
        
        m_depth--;
        
        if(m_pretty_print && !m_first_element[m_depth + 1])
        {
            m_buffer += "\n" + GetIndent();
        }
        
        m_buffer += "}";
        m_in_object = (m_depth > 0);
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 开始JSON数组                                                      |
    //+------------------------------------------------------------------+
    CProfessionalJSON* StartArray()
    {
        AddCommaIfNeeded();
        
        m_buffer += "[";
        m_in_array = true;
        m_depth++;
        
        if(m_depth < ArraySize(m_first_element))
            m_first_element[m_depth] = true;
        
        if(m_pretty_print)
            m_buffer += "\n";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 结束JSON数组                                                      |
    //+------------------------------------------------------------------+
    CProfessionalJSON* EndArray()
    {
        if(!m_in_array)
        {
            Print("JSON Error: EndArray called without matching StartArray");
            return GetPointer(this);
        }
        
        m_depth--;
        
        if(m_pretty_print && !m_first_element[m_depth + 1])
        {
            m_buffer += "\n" + GetIndent();
        }
        
        m_buffer += "]";
        m_in_array = (m_depth > 0);
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加键（仅在对象中使用）                                            |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Key(const string& key)
    {
        if(!m_in_object)
        {
            Print("JSON Error: Key can only be used inside an object");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print)
            m_buffer += GetIndent();
        
        m_buffer += "\"" + EscapeString(key) + "\":";
        
        if(m_pretty_print)
            m_buffer += " ";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加字符串值                                                      |
    //+------------------------------------------------------------------+
    CProfessionalJSON* String(const string& value)
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        m_buffer += "\"" + EscapeString(value) + "\"";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加数字值（整数）                                                 |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Number(long value)
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        m_buffer += IntegerToString(value);
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加数字值（浮点数）                                               |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Number(double value, int precision = -1)
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        if(precision < 0)
            precision = m_decimal_places;
        
        // 智能格式化数字
        if(MathAbs(value - MathRound(value)) < 1e-10)
        {
            m_buffer += IntegerToString((long)MathRound(value));
        }
        else
        {
            string num_str = DoubleToString(value, precision);
            
            // 移除尾部的零
            int len = StringLen(num_str);
            int dot_pos = StringFind(num_str, ".");
            
            if(dot_pos >= 0)
            {
                while(len > dot_pos + 2 && StringGetCharacter(num_str, len - 1) == '0')
                    len--;
                
                if(len == dot_pos + 1)
                    len = dot_pos;
                
                num_str = StringSubstr(num_str, 0, len);
            }
            
            m_buffer += num_str;
        }
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加布尔值                                                        |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Bool(bool value)
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        m_buffer += value ? "true" : "false";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加null值                                                        |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Null()
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        m_buffer += "null";
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 添加原始JSON（用于嵌套已有的JSON）                                  |
    //+------------------------------------------------------------------+
    CProfessionalJSON* Raw(const string& json)
    {
        if(m_in_object && m_first_element[m_depth])
        {
            Print("JSON Error: Value needs a key in object context");
            return GetPointer(this);
        }
        
        AddCommaIfNeeded();
        
        if(m_pretty_print && m_in_array)
            m_buffer += GetIndent();
        
        m_buffer += json;
        
        return GetPointer(this);
    }
    
    //+------------------------------------------------------------------+
    //| 获取JSON字符串                                                    |
    //+------------------------------------------------------------------+
    string GetString()
    {
        return m_buffer;
    }
    
    //+------------------------------------------------------------------+
    //| 设置缩进字符串                                                    |
    //+------------------------------------------------------------------+
    void SetIndentString(const string& indent)
    {
        m_indent_string = indent;
    }
    
    //+------------------------------------------------------------------+
    //| 设置Pretty Print模式                                             |
    //+------------------------------------------------------------------+
    void SetPrettyPrint(bool pretty)
    {
        m_pretty_print = pretty;
    }
    
private:
    //+------------------------------------------------------------------+
    //| 添加逗号（如果需要）                                               |
    //+------------------------------------------------------------------+
    void AddCommaIfNeeded()
    {
        if(m_depth > 0 && m_depth < ArraySize(m_first_element))
        {
            if(!m_first_element[m_depth])
            {
                m_buffer += ",";
                if(m_pretty_print)
                    m_buffer += "\n";
            }
            else
            {
                m_first_element[m_depth] = false;
            }
        }
    }
    
    //+------------------------------------------------------------------+
    //| 获取当前缩进                                                      |
    //+------------------------------------------------------------------+
    string GetIndent()
    {
        if(!m_pretty_print)
            return "";
        
        string indent = "";
        for(int i = 0; i < m_depth; i++)
            indent += m_indent_string;
        
        return indent;
    }
    
    //+------------------------------------------------------------------+
    //| 转义字符串 - 完整的JSON规范实现                                     |
    //+------------------------------------------------------------------+
    string EscapeString(const string& str)
    {
        string result = "";
        int len = StringLen(str);
        
        // 预分配空间以提高性能
        StringReserve(result, len * 2);
        
        for(int i = 0; i < len; i++)
        {
            ushort ch = StringGetCharacter(str, i);
            
            switch(ch)
            {
                case '"':  result += "\\\""; break;
                case '\\': result += "\\\\"; break;
                case '/':  result += "\\/";  break;
                case 8:    result += "\\b";  break;  // Backspace
                case 12:   result += "\\f";  break;  // Form feed
                case 10:   result += "\\n";  break;  // Line feed
                case 13:   result += "\\r";  break;  // Carriage return
                case 9:    result += "\\t";  break;  // Tab
                default:
                    if(ch < 0x20)
                    {
                        // 控制字符 - 使用Unicode转义
                        result += StringFormat("\\u%04X", ch);
                    }
                    else if(ch > 0x7E && ch < 0x10000)
                    {
                        // 非ASCII字符 - 使用Unicode转义
                        result += StringFormat("\\u%04X", ch);
                    }
                    else if(ch >= 0x10000)
                    {
                        // 处理代理对（Surrogate pairs）
                        uint code = ch - 0x10000;
                        ushort high = (ushort)((code >> 10) + 0xD800);
                        ushort low = (ushort)((code & 0x3FF) + 0xDC00);
                        result += StringFormat("\\u%04X\\u%04X", high, low);
                    }
                    else
                    {
                        result += ShortToString(ch);
                    }
                    break;
            }
        }
        
        return result;
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
        json.Key(key1).String(value1);
        
        if(key2 != "")
            json.Key(key2).String(value2);
        
        if(key3 != "")
            json.Key(key3).String(value3);
        
        json.EndObject();
        return json.GetString();
    }
    
    //+------------------------------------------------------------------+
    //| 转义字符串（静态方法）                                             |
    //+------------------------------------------------------------------+
    static string Escape(const string& str)
    {
        CProfessionalJSON json;
        json.String(str);
        string result = json.GetString();
        
        // 移除引号
        return StringSubstr(result, 1, StringLen(result) - 2);
    }
};
