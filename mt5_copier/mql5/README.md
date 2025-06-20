# MT5 Trade Copier - MQL5 Components

## 修复说明

已修复以下编译错误：

### 1. TradeCopierMaster.mq5
- **问题**: ZmqContext和ZmqSocket类型未正确使用
- **修复**: 
  - 使用 `new ZmqSocket(context, ZMQ_REQ)` 替代 `context.Socket(ZMQ_REQ)`
  - 修正了所有指针操作和错误处理
  - 使用 `Zmq::errorNumber()` 替代 `zmq_errno()`
  - 修正了poll操作，使用PollItem结构体

### 2. ProfessionalJSON.mqh
- **问题**: 流畅API的链式调用导致编译错误
- **修复**: 
  - 移除了链式调用，改为独立的方法调用
  - 修正了Key()方法的返回值问题
  - 简化了Escape()方法的实现

### 3. Socket.mqh
- **问题**: sendMore和sendConstMore方法声明但未实现
- **修复**: 添加了这两个方法的完整实现

## 编译步骤

1. **复制文件到MT5数据目录**
   ```
   将 mt5_copier/mql5/ 目录下的所有文件复制到:
   %APPDATA%\MetaQuotes\Terminal\[YOUR_TERMINAL_ID]\MQL5\
   ```

2. **确保目录结构正确**
   ```
   MQL5/
   ├── Experts/
   │   └── TradeCopierMaster.mq5
   ├── Include/
   │   ├── ZmqConfig.mqh
   │   ├── TradeEventSerializer.mqh
   │   ├── ProfessionalJSON.mqh
   │   ├── Mql/
   │   │   └── Lang/
   │   │       ├── Error.mqh
   │   │       ├── GlobalVariable.mqh
   │   │       ├── Mql.mqh
   │   │       └── Native.mqh
   │   └── Zmq/
   │       ├── AtomicCounter.mqh
   │       ├── Context.mqh
   │       ├── Errno.mqh
   │       ├── Socket.mqh
   │       ├── SocketOptions.mqh
   │       ├── Z85.mqh
   │       ├── Zmq.mqh
   │       └── ZmqMsg.mqh
   └── Scripts/
       └── TestCompile.mq5
   ```

3. **安装ZeroMQ库**
   - 下载对应的libzmq.dll文件
   - 将其放置在MT5终端的Libraries目录下

4. **编译测试**
   - 在MT5编辑器中打开 `Scripts/TestCompile.mq5`
   - 按F7编译，确保没有错误
   - 运行脚本验证所有组件工作正常

5. **编译主EA**
   - 打开 `Experts/TradeCopierMaster.mq5`
   - 按F7编译
   - 如果成功，EA就可以使用了

## 使用说明

### EA参数
- `EnableCopier`: 启用/禁用跟单功能
- `HeartbeatIntervalSeconds`: 心跳间隔（秒）

### 通信模式
默认使用IPC模式（高性能本地通信）。如需使用TCP模式（跨设备），请：
1. 编辑 `Include/ZmqConfig.mqh`
2. 取消注释 `#define USE_TCP_MODE`
3. 重新编译EA

### 验证连接
1. 先启动Python控制器
2. 再将EA附加到图表
3. 查看EA日志确认握手成功

## 故障排除

### 编译错误
- 确保所有文件路径正确
- 检查是否缺少依赖文件
- 确认MT5版本支持所有使用的功能

### 运行时错误
- 检查libzmq.dll是否正确安装
- 确认Python端已启动并监听
- 查看EA日志获取详细错误信息

### 性能优化
- 使用IPC模式而非TCP模式
- 调整心跳间隔避免过于频繁
- 监控日志大小，必要时关闭DEBUG_MODE 