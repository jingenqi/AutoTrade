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

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QTextBlock, QTextCursor
from gui.main_window import run_gui

# 注册Qt元类型，解决跨线程信号传递问题
# 在PyQt5中，使用pyqtSignal时会自动注册类型
# 如果仍有问题，可以在main_window.py中处理

if __name__ == "__main__":
    run_gui()
