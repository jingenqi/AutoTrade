# MT5 自动跟单系统测试

本目录包含 MT5 自动跟单系统的测试代码。测试分为三个主要类别：

1. **单元测试** - 测试各个组件的独立功能
2. **GUI测试** - 测试基于PyQt5的用户界面
3. **集成测试** - 测试组件之间的交互

## 测试结构

```
tests/
├── unit/               # 核心组件的单元测试
│   └── core/           # 核心功能测试
│       ├── test_account_manager.py
│       ├── test_events.py
│       ├── test_trade_engine.py
│       └── test_worker_process.py
├── gui/                # GUI组件测试
│   ├── test_account_dialog.py
│   └── test_main_window.py
├── integration/        # 集成测试
│   └── test_ea_contract.py
├── mock_ea.py          # 用于测试的模拟EA
└── TESTING_STRATEGY.md # 总体测试策略
```

## 运行测试

### 运行所有测试

Windows系统:
```
cd mt5_copier
run_tests.bat
```

Unix类系统:
```
cd mt5_copier
chmod +x run_tests.sh
./run_tests.sh
```

### 运行特定测试类别

仅运行单元测试:
```
python -m pytest tests/unit -v
```

仅运行GUI测试:
```
python -m pytest tests/gui -v
```

仅运行集成测试:
```
python -m pytest tests/integration -v
```

### 运行特定测试文件

```
python -m pytest tests/unit/core/test_trade_engine.py -v
```

### 运行特定测试函数

```
python -m pytest tests/unit/core/test_trade_engine.py::TestTradeResultHandling::test_on_trade_executed_updates_position_map_on_open -v
```

## 使用真实MT5进行测试

某些测试需要运行真实的MT5终端。默认情况下，这些测试会被跳过，除非设置了必要的环境变量：

```
# Windows
set MT5_TERMINAL_PATH=C:\path\to\terminal64.exe
set MT5_LOGIN=12345678

# Unix类系统
export MT5_TERMINAL_PATH=/path/to/terminal64.exe
export MT5_LOGIN=12345678
```

然后运行测试:
```
python -m pytest tests/unit/core/test_worker_process_mt5.py -v
```

## 模拟EA

`mock_ea.py` 脚本模拟了MQL5专家顾问(EA)用于测试目的。它可以用来测试Python控制器处理各种交易事件的能力：

```
python tests/mock_ea.py --iterations 3
```

## 使用真实EA进行集成测试

使用真实MT5 EA进行测试：

1. 在MetaTrader 5中编译并加载 `TradeCopierMaster.mq5` EA
2. 运行集成测试工具：
   ```
   python -m pytest tests/integration/test_ea_contract.py -v
   ```
3. 在MT5中执行交易操作并观察测试结果

## 测试覆盖率

生成测试覆盖率报告：

```
python -m pytest --cov=python tests/
```

生成HTML覆盖率报告：

```
python -m pytest --cov=python --cov-report=html tests/
```

HTML报告将生成在 `htmlcov` 目录中。 