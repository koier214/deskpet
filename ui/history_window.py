"""聊天记录窗口 —— 纯文本历史记录：微信式，旧的在上、新的在下

标准窗口（有标题栏）。排序规则与聊天窗一致（2026-09-14 统一）：
  历史加载：按时间戳排成正序逐行追加，最新一条自然落在最下面
  实时消息：追加到底部（从底部弹出）
  打开窗口 / 来新消息：都自动滚到底部定位到最新一条
"""
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel

from ui.chat_window import chronological
from ui import theme

WIN_W, WIN_H = 340, 460


class HistoryWindow(QWidget):
    """右键"聊天记录"打开的历史记录窗"""

    def __init__(self, identity='yier', parent=None):
        super().__init__(parent)
        self._identity = identity

        self.setWindowTitle('一二布布 聊天记录')
        self.resize(WIN_W, WIN_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self._hint = QLabel('旧的在上、新的在下；打开时自动加载最近 20 条并定位到最新')
        self._hint.setStyleSheet(f'font-size: 11px; color: {theme.TEXT_DIM};')
        layout.addWidget(self._hint)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setStyleSheet(
            f'font-size: 13px; color: {theme.TEXT}; background: {theme.CARD}; '
            f'border: 1px solid {theme.CARD_BORDER}; border-radius: 8px; padding: 6px;')
        self.setStyleSheet(f'{type(self).__name__} {{ background: {theme.BG}; }}')
        layout.addWidget(self._text)

    # ---------- 对外接口 ----------

    def clear(self):
        """清空显示（重新打开时先清空再加载，避免重复）"""
        self._text.clear()

    def append_history(self, messages):
        """追加历史：按时间正序逐行写到底部，最新一条落在最下面"""
        if not messages:
            self._text.append('（暂无聊天记录）')
            return
        for m in chronological(messages):
            self._append_msg(
                m.get('sender', ''), m.get('content', ''), m.get('timestamp'))
        self._scroll_to_bottom()

    def append_message(self, sender, content, timestamp=None):
        """实时消息追加到底部（从底部弹出），并滚到最新"""
        self._text.append(self._make_line(sender, content, timestamp))
        self._scroll_to_bottom()

    # ---------- 内部 ----------

    def showEvent(self, event):
        """每次打开都定位到最新消息（和聊天窗一致）"""
        super().showEvent(event)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        """滚到底部看最新一条；布局更新后再补一次，避免停在半路"""
        self._do_scroll_to_bottom()
        QTimer.singleShot(0, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self):
        bar = self._text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append_msg(self, sender, content, timestamp):
        self._text.append(self._make_line(sender, content, timestamp))

    def _make_line(self, sender, content, timestamp):
        """格式化一行 [HH:MM] 谁 说：内容"""
        who = '我' if sender == self._identity else sender
        time_str = ''
        if timestamp:
            time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M') + ' '
        return f'[{time_str}{who} 说] {content}'
