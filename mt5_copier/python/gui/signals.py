from PyQt5.QtCore import QObject, pyqtSignal

class GuiConnectionSignal(QObject):
    update_log = pyqtSignal(str, str)
    update_account_status = pyqtSignal(dict) 