@echo off
echo 运行 MT5 自动跟单系统测试
echo ==============================

REM 设置Python路径包含项目根目录
set PYTHONPATH=%PYTHONPATH%;..

REM 运行单元测试
echo 运行单元测试...
python -m pytest unit -v

REM 运行GUI测试
echo.
echo 运行GUI测试...
python -m pytest gui -v

REM 运行集成测试
echo.
echo 运行集成测试...
python -m pytest integration -v

echo.
echo 所有测试已完成。 