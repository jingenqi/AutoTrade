# MT5 Trade Copier - 故障排除指南

## 快速诊断

运行诊断工具以快速检查系统状态：

```bash
# Windows
diagnose.bat

# Linux/Mac
python python/diagnose.py
```

## 常见问题及解决方案

### 1. 跟单账户不执行交易

**症状**：主账户交易事件能够被捕获，但跟单账户没有执行相应的交易。

**可能原因和解决方案**：

- **符号映射问题**：
  - 检查配置文件中的 `symbol_mapping` 是否正确。
  - 使用诊断工具 (`diagnose.bat`) 检查符号映射是否正确。
  - 确保跟单账户能够访问映射后的符号。

- **工作进程未启动**：
  - 检查日志中是否有 "工作进程启动成功" 的消息。
  - 确保配置文件中的 `terminal_path` 路径正确。
  - 确保MT5终端已安装并且可以手动启动。

- **符号信息获取失败**：
  - 检查日志中是否有 "无法获取品种信息" 的错误。
  - 确保跟单账户中存在该交易品种。
  - 尝试在跟单账户的MT5终端中手动搜索该品种。

- **交易执行失败**：
  - 检查日志中是否有交易执行失败的错误消息。
  - 确认跟单账户有足够的余额和保证金。
  - 检查跟单账户的交易权限设置。

### 2. MT5 终端连接问题

**症状**：无法连接到MT5终端或初始化失败。

**可能原因和解决方案**：

- **终端路径错误**：
  - 确保配置文件中的 `terminal_path` 指向正确的 terminal64.exe 文件。
  - 检查路径是否包含空格，如果有，确保正确处理。

- **账户信息错误**：
  - 验证登录ID、密码和服务器信息是否正确。
  - 尝试手动登录MT5终端，确认账户信息有效。

- **MT5 API安装问题**：
  - 确保已安装正确版本的 MetaTrader5 Python 包。
  - 运行 `pip install --upgrade MetaTrader5` 更新到最新版本。

### 3. ZMQ 通信问题

**症状**：主账户和跟单账户之间的通信失败。

**可能原因和解决方案**：

- **ZMQ配置错误**：
  - 检查配置文件中的 ZMQ 设置是否正确。
  - 确保端口未被其他应用程序占用。

- **EA未正确安装**：
  - 确保主账户MT5中已正确安装EA。
  - 检查EA日志，确认其正在发送事件。

- **防火墙或安全软件阻止**：
  - 检查防火墙设置，确保允许MT5和Python进程之间的通信。
  - 临时禁用安全软件，测试是否解决问题。

### 4. 符号映射问题

**症状**：交易复制失败，日志中显示符号信息获取失败。

**可能原因和解决方案**：

- **符号名称不一致**：
  - 主账户和跟单账户可能使用不同的符号命名。
  - 在配置文件的 `symbol_mapping` 中正确映射符号。
  - 例如：`"EURUSD": "EURUSD-ECN"` 将主账户的 EURUSD 映射到跟单账户的 EURUSD-ECN。

- **符号不可用**：
  - 确保跟单账户中可以交易映射后的符号。
  - 在MT5市场观察中添加所需的符号。

- **符号规格不同**：
  - 主账户和跟单账户的符号可能有不同的点值、手数要求等。
  - 调整配置中的 `lot_value` 以适应不同的规格。

### 5. 诊断工具使用

如果遇到问题，请运行诊断工具获取更详细的信息：

1. 运行 `diagnose.bat`
2. 查看输出的诊断结果
3. 根据诊断结果修复问题

### 6. 日志分析

分析日志文件可以帮助识别问题：

- 检查 `logs/gui.log` 获取GUI相关错误
- 查看 `logs/trade_copier.log` 获取交易相关错误
- 寻找关键词如 "错误"、"失败"、"无法连接" 等

## 高级故障排除

### 手动验证符号映射

1. 启动主账户和跟单账户的MT5终端
2. 在市场观察中搜索相关符号
3. 比较符号属性（点值、合约大小等）
4. 根据差异调整配置

### 检查网络连接

1. 确保所有组件在同一网络上
2. 检查端口是否开放：`netstat -ano | findstr 5555`
3. 测试本地连接：`telnet localhost 5555`

### 重置系统

如果所有方法都失败，可以尝试完全重置系统：

1. 关闭所有MT5终端和跟单程序
2. 删除 `trade_state.json` 文件
3. 重启计算机
4. 重新启动MT5终端和跟单程序

## 联系支持

如果以上方法无法解决问题，请联系技术支持并提供以下信息：

1. 完整的日志文件
2. 诊断工具的输出结果
3. 配置文件（请删除敏感信息如密码）
4. 问题的详细描述和重现步骤

## 日志文件位置

- GUI日志：`logs/gui.log`
- 交易状态：`trade_state.json`
- 工作进程日志：查看控制台输出

## 最佳实践

1. **启动顺序：**
   - 先启动所有MT5终端
   - 确保主账户EA正在运行
   - 最后启动跟单GUI

2. **配置检查：**
   - 运行诊断工具验证配置
   - 确保所有路径都是绝对路径
   - 定期备份 config.json

3. **性能优化：**
   - 使用IPC代替TCP（如果在同一台机器上）
   - 减少不必要的日志记录
   - 合理设置利润更新间隔

## 需要更多帮助？

如果问题仍未解决：

1. 运行诊断工具并保存输出
2. 收集相关日志文件
3. 记录具体的错误信息和重现步骤
4. 检查EA的日志输出（MT5终端的"专家"标签页） 

flowchart TB
    subgraph "主账户MT5"
        Master[主账户MT5终端]
        EA[TradeCopierMaster EA]
        Master --> EA
    end
    
    subgraph "通信层"
        ZMQ[ZeroMQ<br/>REQ/REP + PUB/SUB]
        EA -->|"交易事件"| ZMQ
    end
    
    subgraph "Python控制器"
        Listener[ZMQ监听器]
        Engine[交易引擎]
        AccMgr[账户管理器]
        History[交易历史]
        Risk[风险管理器]
        
        ZMQ -->|"接收事件"| Listener
        Listener --> Engine
        Engine --> AccMgr
        Engine --> History
        Engine --> Risk
        
        subgraph "工作进程池"
            W1[Worker 1]
            W2[Worker 2]
            W3[Worker N]
        end
        
        AccMgr --> W1
        AccMgr --> W2
        AccMgr --> W3
    end
    
    subgraph "跟单账户"
        MT1[MT5终端1]
        MT2[MT5终端2]
        MT3[MT5终端N]
        
        W1 --> MT1
        W2 --> MT2
        W3 --> MT3
    end
    
    subgraph "GUI界面"
        Dashboard[仪表板]
        Accounts[账户管理]
        Mapping[品种映射]
        HistoryView[历史查询]
        RiskView[风险控制]
        
        Engine -.->|"状态更新"| Dashboard
        AccMgr -.->|"账户信息"| Accounts
        History -.->|"交易记录"| HistoryView
        Risk -.->|"风险状态"| RiskView
    end
    
    subgraph "数据存储"
        DB[(SQLite数据库)]
        State[状态文件]
        Config[配置文件]
        
        History --> DB
        Engine --> State
        Risk --> Config
    end
    
    style Master fill:#f9f,stroke:#333,stroke-width:4px
    style Engine fill:#bbf,stroke:#333,stroke-width:4px
    style Dashboard fill:#bfb,stroke:#333,stroke-width:4px
    style Risk fill:#fbb,stroke:#333,stroke-width:4px