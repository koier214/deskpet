"""系统级全局热键（Windows）—— ctypes 直调 Win32 RegisterHotKey，零 pip 依赖

原理：Windows 把热键消息 WM_HOTKEY 投递到注册它的线程，
Qt 的 QAbstractNativeEventFilter 拦住该消息后发 triggered 信号。
注册失败（如 Alt+Q 被其他程序占用）时自动降级为应用内快捷键。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

MOD_ALT = 0x0001      # Win32 修饰键常量：Alt
WM_HOTKEY = 0x0312    # Windows 消息编号：热键被按下
HOTKEY_ID = 0xB9A1    # 本程序热键的注册编号（自选唯一值）


class _HotkeyFilter(QAbstractNativeEventFilter):
    """拦 Windows 消息队列：匹配到 WM_HOTKEY 就回调"""

    def __init__(self, hotkey_id, callback):
        super().__init__()
        self._id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        # message 是 MSG 结构体指针，转成 ctypes 结构读出消息编号
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self._id:
            self._callback()
        return False, 0   # 不拦截其他消息，交还 Qt 正常处理


class GlobalHotkey(QObject):
    """Alt+Q 全局热键（系统级，任何软件里按都有效）"""

    triggered = Signal()   # 热键按下时发出

    def __init__(self, key='q', modifiers=MOD_ALT, parent=None):
        super().__init__(parent)
        self._filter = None
        self._fallback = None

        if sys.platform == 'win32':
            # hWnd 传 None = 消息投递到当前（GUI）线程的消息队列
            ok = ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, modifiers, ord(key.upper()))
            if ok:
                self._filter = _HotkeyFilter(HOTKEY_ID, self.triggered.emit)
                QApplication.instance().installNativeEventFilter(self._filter)
                return

        # 非 Windows 平台，或注册失败（热键被占用）→ 降级为应用内快捷键。
        # QShortcut 必须挂在一个 widget 上才生效，所以构造时要传 parent
        #（PetWindow 传自己）；parent 为 None 时降级Shortcut 无法工作，直接报错比静默失效好查
        if parent is None:
            raise ValueError('GlobalHotkey 需要一个 widget 作为 parent（降级快捷键要挂上去）')
        self._fallback = QShortcut(QKeySequence(f'Alt+{key.upper()}'), parent)
        self._fallback.setContext(Qt.ApplicationShortcut)
        self._fallback.activated.connect(self.triggered.emit)

    def unregister(self):
        """退出时释放系统热键"""
        if self._filter is not None:
            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            QApplication.instance().removeNativeEventFilter(self._filter)
            self._filter = None
        if self._fallback is not None:
            self._fallback.setEnabled(False)
            self._fallback = None
