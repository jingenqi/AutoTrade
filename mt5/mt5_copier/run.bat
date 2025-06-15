@echo off
REM Batch script to run pytest for the MT5 Trade Copier project.

REM Change to the directory where the script is located to ensure paths are correct.
cd /D "%~dp0"

echo "Running all unit tests with pytest..."

REM -v for verbose, --color=yes to force color, specify the tests directory.
python -m pytest -v --color=yes tests/ 