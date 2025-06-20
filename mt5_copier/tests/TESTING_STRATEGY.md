# 项目测试策略

本文档概述了本项目中使用的两种主要测试方法，以确保系统的稳健性和正确性。这两种方法都至关重要，且各有其特定目的。

## 方法一：单元测试与模拟集成测试

此方法用于在完全隔离的环境中测试系统的Python组件，无需运行MetaTrader 5终端。

- **涉及组件**:
    - `run.bat`: 单元测试的执行脚本。
    - `tests/test_validation_logic.py`: 针对Pydantic数据模型的单元测试。
    - `tests/mock_ea.py`: 一个功能完备的MQL5智能交易（EA）模拟器。
    - `tests/test_zmq_connection.py`: 扮演Python控制器角色的测试验证工具。

- **目的**:
    - **快速与便捷**: 允许在没有启动和操作MT5终端的开销下，快速开发和测试Python控制器、GUI及业务逻辑。
    - **逻辑验证**: 验证Python代码能够正确处理所有预期的数据，包括所有订单类型和错误情况。

- **如何运行**:
    1.  **单元测试**:
        ```powershell
        # 在 mt5_copier/ 目录下执行
        .\run.bat
        ```
    2.  **模拟集成测试**:
        - 终端 1: `python tests/test_zmq_connection.py`
        - 终端 2: `python tests/mock_ea.py --iterations 3`

## 方法二：契约测试与真实集成测试

这是确保MQL5 EA和Python控制器能够正确通信的**最关键**的测试。它直接验证MQL5/C++代码生成的JSON是否符合我们定义的数据契约。

- **涉及组件**:
    - `TradeCopierMaster.mq5` (在MetaEditor中编译的**真实**智能交易程序)。
    - `tests/test_zmq_connection.py`: 同一个测试验证工具，但此次用于验证来自真实EA的消息。

- **目的**:
    - **契约履行**: 证明`.mqh`头文件（特别是 `ProfessionalJSON.mqh` 和 `TradeEventSerializer.mqh`）正确地实现了JSON规范。
    - **端到端验证**: 验证从一个实时运行的MT5终端到Python应用程序的完整通信链路。

- **如何运行**:
    1.  确保 `TradeCopierMaster.mq5` 已在MetaEditor中成功编译且无错误。
    2.  **在终端中**，启动测试验证工具：
        ```powershell
        python mt5_copier/tests/test_zmq_connection.py
        ```
    3.  **在MetaTrader 5中**，将 `TradeCopierMaster` EA加载到一个图表上。
    4.  在终端中执行交易操作，并观察测试验证工具的输出。每一个 `[PASS]` 都代表着对MQL5代码输出的一次成功验证。 