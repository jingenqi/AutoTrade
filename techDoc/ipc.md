┌──────────────────────────────────────────────────────┐
│                 本 地 机 器（Windows 10 / 11）          │
│                                                      │
│  ┌───────────────┐    IPC             ┌────────────┐ │
│  │ 主账户 MT5 EA │───PUB──────────────▶│Python控制器│ │
│  │ (OnTradeTrans │<──SUB──────────────│(ZmqListener)│ │
│  │ + ZMQ PUB/REQ)│   ipc://mt5_trade… │  + TradeEng │ │
│  └───────────────┘   ipc://mt5_sync…  └────┬───────┘ │
│                                            │         │
│                             MT5 Python API │         │
│                                            │         │
│   ┌──────────────┐         ┌──────────────┐│         │
│   │ 副账户 #1     │         │ 副账户 #2     ││         │
│   │ terminal64 – │         │ terminal64 – ││         │
│   │ /portable    │         │ /portable    ││         │
│   └──────────────┘         └──────────────┘│         │
│                                            │         │
│  ┌──────────────────────────────────────────▼──────┐ │
│  │                PyQt5 桌面 GUI                   │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘

## 功能与约束
| 功能   | 说明                                     |
| ---- | -------------------------------------- |
| 事件捕获 | 主账户 EA 用 `OnTradeTransaction` 毫秒级监听    |
| 事件分发 | EA→Python 经 IPC  Pub/Sub (**无轮询**)     |
| 策略   | 副 #1 正向复制 副 #2 反向镜像（含 SL/TP 互换）        |
| 订单类型 | 市价、Limit/Stop 挂单全覆盖                    |
| GUI  | 账户表、策略参数、启动/停止、持仓&日志监控                 |
| 日志   | 每笔交易 JSON/CSV 双格式本地落盘，含延迟统计            |
| 并发   | 默认线程池并行两副账户下单；可扩容                      |
| 延迟   | 主→副 ≤ 5 ms（平均 2–3 ms；IPC 实测 18 µs RTT） |
| 热更新  | GUI 改动即写入 `config.json`；可手动重载          |

## IPC ZeroMQ 协议
| 通道 | 模式               | 端点（Win）                                        | 消息体              | 作用          |
| -- | ---------------- | ---------------------------------------------- | ---------------- | ----------- |
| 握手 | EA=REQ / CTL=REP | `ipc://mt5_sync.ipc` → `\\.\pipe\mt5_sync.ipc` | `READY?` ⇄ `ACK` | 启动同步 & 心跳备用 |
| 事件 | EA=PUB / CTL=SUB | `ipc://mt5_trade_bus.ipc`                      | JSON 交易事件        | 实时推送交易      |


# 模块设计
## 主账户
| 函数                   | 关键逻辑                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `OnInit`             | 1. `ContextNew`  2. `SocketNew(ZMQ_REQ)`→`connect(SYNC_URI)` 3. `SocketNew(ZMQ_PUB)`→`bind(BUS_URI)` 4. 握手 REQ→`READY?` ← `ACK` |
| `OnTradeTransaction` | - 过滤 `DEAL_ADD/ORDER_*` <br>- 构造 JSON `{event_type,symbol,action,volume,price,sl,tp,timestamp}`<br>- `SocketSend(pubSock,json)` |
| `OnTimer` (可选)       | 每 5 s 发心跳                                                                                                                       |
| `OnDeinit`           | 关闭两个套接字 + `ContextTerm`                                                                                                         |

## Python控制器
| 类                              | 方法                            | 职责                                                                                                                                |
| ------------------------------ | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **ZmqListener**                | `start()`                     | ① REP 握手；② SUB 阻塞 `recv`→`json.loads`→ `TradeEngine.process_event`                                                                |
| **AccountManager**             | `send_order(acc_id, request)` | `mt5.initialize(path…)`→`login`→`order_send`；返回 `(ok,result)`                                                                     |
| **TradeEngine**                | `process_event(evt)`          | - 根据 `evt["event_type"]` 分派<br>- 对启用账户生成 request<br>- 正向/反向逻辑 & 手数计算<br>- 并行 `AccountManager.send_order`<br>- 更新 `trade_map` & 日志 |
| **Logger**                     | `log(record)`                 | JSON/CSV 双写；GUI 追加文本                                                                                                              |
| **GuiController(QMainWindow)** | Qt UI                         | 账户表(QTableView)·启动按钮·持仓表·日志窗口                                                                                                     |

# 核心算法
| 场景         | 正向账户 (#1)   | 反向账户 (#2)   |
| ---------- | ----------- | ----------- |
| 市价 BUY     | BUY 同手数     | SELL，同手数或倍数 |
| BUY\_LIMIT | BUY\_LIMIT  | SELL\_STOP  |
| SL/TP 同步   | SL=SL TP=TP | SL⇄TP 互换    |
| 平仓         | 同步市价平仓      | 同步市价平仓      |
| 部分成交       | 按部分量复制      | 部分量镜像复制     |

# GUi架构
| 选项卡   | 组件                                                          | 说明                     |
| ----- | ----------------------------------------------------------- | ---------------------- |
| 账户管理  | `QTableWidget` 9 列（启用/ID/服务器/路径/模式/手数模式/值/同步SLTP/状态） + 增删按钮 | 实时写 config.json        |
| 控制&监控 | `QPushButton`(Start/Stop) + `QTableView`(持仓同步) + 账户状态面板     | 与后台信号槽通信               |
| 日志    | `QPlainTextEdit` 只读                                         | 后台 logger emit → 槽函数追加 |

# 并发模型
GUI 主线程
后台 QThread 运行 ZmqListener + TradeEngine
下单时通过 ThreadPoolExecutor(max_workers=len(enabled_accounts)) 并行调用 AccountManager.send_order

# 