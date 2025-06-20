@echo off
setlocal

REM Batch script to run tests for the MT5 Trade Copier project.
REM Change to the directory where the script is located to ensure paths are correct.
cd /D "%~dp0"
echo Running tests from: %cd%

REM PYTHONPATH is now handled by pytest.ini, no need to set it here.

echo.
echo Using Python at:
where python
echo.

REM Check for pytest
python -m pytest --version >nul 2>&1
if %errorlevel% neq 0 (
    echo pytest not found or not working. Please check your Python environment.
    echo You can try installing it with: pip install pytest pytest-qt pytest-mock
    exit /b 1
)

REM --- EXECUTION SECTION ---
echo MT5 Trade Copier Test Runner
echo ===========================

if "%1"=="" (
  call :run_all_tests
) else (
  call :run_selected_tests %*
)
goto :eof

REM --- SUBROUTINES ---

:run_all_tests
echo Running all tests with pytest...
REM -v for verbose, -s to show prints, -x to stop on first failure
python -m pytest -xvs --color=yes tests\
if %errorlevel% neq 0 (
    echo Some tests failed with error code %errorlevel%
)
exit /b %errorlevel%


:run_selected_tests
setlocal EnableDelayedExpansion
echo Running selected tests...
set "prefixed_files="

for %%f in (%*) do (
    set "file=%%~f"
    set "file=!file:/=\!"
    if /i "!file:~0,6!" NEQ "tests\" (
        set "prefixed_files=!prefixed_files! tests\!file!"
    ) else (
        set "prefixed_files=!prefixed_files! !file!"
    )
)

echo.
echo pytest arguments: !prefixed_files!
echo.
python -m pytest -xvs --color=yes !prefixed_files!
if %errorlevel% neq 0 (
    echo Some tests failed with error code %errorlevel%
)
endlocal
exit /b %errorlevel%
