# 项目测试策略

本文档概述了本项目中使用的几种主要测试方法，以确保系统的稳健性和正确性。这些方法都至关重要，且各有其特定目的。

## 方法一：单元测试

此方法用于测试系统各个组件的独立功能，确保每个组件都能正确工作。

- **涉及组件**:
    - `tests/unit/core/`: 核心组件的单元测试，包括账户管理器、交易引擎、事件处理等。
    - `tests/unit/core/test_worker_process.py`: 工作进程的单元测试。
    - `tests/unit/core/test_account_manager.py`: 账户管理器的单元测试。
    - `tests/unit/core/test_trade_engine.py`: 交易引擎的单元测试。

- **目的**:
    - **组件验证**: 验证各个组件的功能是否正确。
    - **边界条件测试**: 测试各种边界条件和错误情况的处理。

- **如何运行**:
    ```powershell
    # 在 mt5_copier/tests/ 目录下执行
    python -m pytest unit -v
    ```

## 方法二：GUI测试

此方法用于测试系统的用户界面组件，确保用户交互功能正常。

- **涉及组件**:
    - `tests/gui/test_account_dialog.py`: 账户配置对话框的测试。
    - `tests/gui/test_main_window.py`: 主窗口的测试。

- **目的**:
    - **界面功能验证**: 验证界面组件的功能是否正确。
    - **用户交互测试**: 测试用户交互流程是否顺畅。

- **如何运行**:
    ```powershell
    # 在 mt5_copier/tests/ 目录下执行
    python -m pytest gui -v
    ```

## 方法三：模拟集成测试

此方法使用模拟EA来测试系统的集成功能，无需运行真实的MetaTrader 5终端。

- **涉及组件**:
    - `tests/mock_ea.py`: 一个功能完备的MQL5智能交易（EA）模拟器。
    - `tests/integration/test_ea_contract.py`: 测试EA和Python控制器之间的通信契约。

- **目的**:
    - **快速与便捷**: 允许在没有启动和操作MT5终端的开销下，快速测试系统的集成功能。
    - **事件处理验证**: 验证系统能够正确处理各种交易事件。

- **如何运行**:
    ```powershell
    # 在 mt5_copier/tests/ 目录下执行
    python mock_ea.py --iterations 3
    ```

## 方法四：真实集成测试

这是确保MQL5 EA和Python控制器能够正确通信的**最关键**的测试。它直接验证MQL5/C++代码生成的JSON是否符合我们定义的数据契约。

- **涉及组件**:
    - `mql5/Experts/TradeCopierMaster.mq5` (在MetaEditor中编译的**真实**智能交易程序)。
    - `tests/integration/test_ea_contract.py`: 测试EA和Python控制器之间的通信契约。

- **目的**:
    - **契约履行**: 证明`.mqh`头文件（特别是 `ProfessionalJSON.mqh` 和 `TradeEventSerializer.mqh`）正确地实现了JSON规范。
    - **端到端验证**: 验证从一个实时运行的MT5终端到Python应用程序的完整通信链路。

- **如何运行**:
    1. 确保 `TradeCopierMaster.mq5` 已在MetaEditor中成功编译且无错误。
    2. **在终端中**，启动集成测试：
        ```powershell
        python -m pytest tests/integration/test_ea_contract.py -v
        ```
    3. **在MetaTrader 5中**，将 `TradeCopierMaster` EA加载到一个图表上。
    4. 在终端中执行交易操作，并观察测试输出。每一个 `[PASS]` 都代表着对MQL5代码输出的一次成功验证。

## 方法五：实际MT5 API测试

此方法用于测试系统与真实MT5 API的交互，确保系统能够正确地执行交易操作。

- **涉及组件**:
    - `tests/unit/core/test_worker_process_mt5.py`: 使用真实MT5 API的工作进程测试。

- **目的**:
    - **API交互验证**: 验证系统能够正确地与MT5 API交互。
    - **交易执行验证**: 验证系统能够正确地执行交易操作。

- **如何运行**:
    1. 设置必要的环境变量：
        ```powershell
        # Windows
        set MT5_TERMINAL_PATH=C:\path\to\terminal64.exe
        set MT5_LOGIN=12345678

        # Unix类系统
        export MT5_TERMINAL_PATH=/path/to/terminal64.exe
        export MT5_LOGIN=12345678
        ```
    2. 运行测试：
        ```powershell
        python -m pytest tests/unit/core/test_worker_process_mt5.py -v
        ```

## 运行所有测试

可以使用以下命令一次性运行所有测试：

```powershell
# 在 mt5_copier/tests/ 目录下执行
./run.bat  # Windows
./run.sh   # Unix类系统
``` 