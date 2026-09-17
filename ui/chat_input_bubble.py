"""聊天输入气泡 —— Alt+Q 唤出，回车发送，隐藏时草稿暂存

与 ChatBubble 的区别：本气泡需要键盘焦点（要打字），
所以不加 WA_ShowWithoutActivating，显示时主动激活窗口。
隐藏只是 hide()，输入框文字自然保留 = 草稿暂存。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit

from ui import theme

BUBBLE_W = 260   # 与 ChatBubble 同宽
BUBBLE_H = 76


class ChatInputBubble(QWidget):
    """悬浮在一二头顶的输入气泡"""

    sig_send = Signal(str)   # 回车发送时发出（已 strip 的非空文字）

    def __init__(self, peer='bubu', parent=None):
        super().__init__(parent)

        # 窗口属性：无边框、置顶、不在任务栏（同 ChatBubble）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(BUBBLE_W, BUBBLE_H)

        # 气泡本体：和待办气泡/白色消息卡同一张脸（theme.CARD_SPEC['panel']）
        self._bubble = QWidget(self)
        self._bubble.setObjectName('bubble')
        self._bubble.setStyleSheet(theme.surface_qss('panel', 'bubble'))
        self._bubble.setFixedSize(BUBBLE_W, BUBBLE_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._bubble)

        layout = QVBoxLayout(self._bubble)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._title = QLabel(f'发给 {peer}：')
        self._title.setStyleSheet(
            f'border: none; font-size: 12px; font-weight: bold; color: {theme.ACCENT_DARK};')

        self._edit = QLineEdit()
        self._edit.setPlaceholderText('输入消息，回车发送（Alt+Q 关闭）')
        self._edit.setStyleSheet(
            f'border: 1px solid {theme.CARD_BORDER}; border-radius: 6px; '
            f'font-size: 12px; color: {theme.TEXT}; padding: 3px; background: {theme.BG};'
        )
        self._edit.returnPressed.connect(self._on_return)

        layout.addWidget(self._title)
        layout.addWidget(self._edit)

    def focus_edit(self):
        """显示后把键盘焦点交给输入框，可立即打字"""
        self._edit.setFocus()

    def _on_return(self):
        """回车：非空则发信号，然后清空输入框（保持打开，可连发）"""
        text = self._edit.text().strip()
        if text:
            self.sig_send.emit(text)
        self._edit.clear()
