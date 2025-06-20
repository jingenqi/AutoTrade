"""
MT5 Trade Copier - GUI Launcher
"""
import os
import sys

# --- 将当前工作目录设置为脚本所在位置 ---
# 这确保了日志、配置文件等的相对路径能够可靠工作。
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
# -------------------------------------------------------------

from gui.main_window import run_gui

if __name__ == "__main__":
    run_gui()
