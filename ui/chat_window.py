"""聊天窗口 —— 微信式聊天气泡窗：布布在左（棕色气泡），我在右（白色气泡）

窗口样式与待办气泡一致（无边框置顶），大小 340×220（高与待办气泡一致）。
浅灰背景衬托白色气泡；排序按微信来：旧的在上、新的在下，实时消息从底部追加进来，
打开窗口自动滚到最新一条；底部输入框回车发送；标题条可拖动，× 关闭。

定位由 PetWindow 统一负责：一二移动时调 `anchor_to(锚点)` 让本窗跟随；
用户拖过标题条后，拖出来的相对偏移会被记住（`_user_offset`），
跟随仍生效，只是锚点上加了这个偏移——手动摆放和跟随不打架。
"""
from datetime import datetime
from html import escape

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea,
)

from ui import theme

WIN_W, WIN_H = 340, 220   # 宽度保持原聊天窗，高度与待办气泡一致
BUBBLE_MAX_W = 220

BROWN = theme.ACCENT   # 布布气泡：棕色底白字（与菜单主色同一棕）
BUBBLE_ME = f'''
    background: {theme.CARD}; border: 1px solid {theme.CARD_BORDER};
    border-radius: 8px; padding: 6px 10px;
    font-size: 12px; color: {theme.TEXT};
'''
BUBBLE_PEER = f'''
    background: {BROWN};
    border-radius: 8px; padding: 6px 10px;
    font-size: 12px; color: #ffffff;
'''


def chronological(messages):
    """把一批历史消息统一成时间正序（旧 → 新），聊天窗/记录窗共用。

    服务器约定返回新→旧，但与其赌每一端的顺序，不如直接按时间戳排：
    有时间戳就升序排；整批都没时间戳时才按服务器约定反着来。
    """
    if any(m.get('timestamp') for m in messages):
        return sorted(messages, key=lambda m: m.get('timestamp') or 0)
    return list(reversed(messages))


class ChatWindow(QWidget):
    """右键"聊天窗口"打开的常驻聊天气泡"""

    sig_send = Signal(str)   # 底部输入框回车发送（已 strip 的非空文字）
    sig_close_requested = Signal()   # 点了 ×；由 PetWindow 负责隐藏并恢复头顶气泡

    def __init__(self, identity='yier', parent=None):
        super().__init__(parent)
        self._identity = identity
        self._dragging = False
        self._drag_offset = None
        self._drag_start_pos = None
        self._user_offset = (0, 0)

        # 无边框置顶气泡（同待办气泡）；需要输入焦点，所以不加 WA_ShowWithoutActivating
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(WIN_W, WIN_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 气泡本体：暖奶油底，衬托白色/棕色消息气泡
        self._bg = QWidget(self)
        self._bg.setObjectName('chatBg')
        self._bg.setStyleSheet(f'''
            #chatBg {{
                background: {theme.BG};
                border: 1px solid {theme.CARD_BORDER};
                border-radius: 12px;
            }}
        ''')
        self._bg.setFixedSize(WIN_W, WIN_H)
        outer.addWidget(self._bg)

        inner = QVBoxLayout(self._bg)
        inner.setContentsMargins(8, 6, 8, 8)
        inner.setSpacing(6)

        # ---- 标题条（按住可拖动窗口） ----
        self._title = QLabel('一二布布 聊天')
        self._title.setStyleSheet(f'font-size: 12px; color: {theme.TEXT_DIM}; border: none;')
        self._title.installEventFilter(self)   # 在标题条上按下鼠标 = 拖动窗口
        self._close_btn = QPushButton('×')
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setStyleSheet(f'''
            QPushButton {{ border: none; color: {theme.TEXT_DIM}; font-size: 14px; }}
            QPushButton:hover {{ color: {theme.RUN_RED}; }}
        ''')
        self._close_btn.clicked.connect(self.sig_close_requested.emit)
        title_row = QHBoxLayout()
        title_row.addWidget(self._title)
        title_row.addStretch()
        title_row.addWidget(self._close_btn)
        inner.addLayout(title_row)

        # ---- 消息列表（滚动区，微信式：旧的在上、新的在下） ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet('background: transparent; border: none;')
        self._list = QWidget()
        self._list.setStyleSheet('background: transparent;')
        self._list_layout = QVBoxLayout(self._list)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()   # 底部弹簧：消息都排在它上面，所以列表末尾 = 最新
        self._scroll.setWidget(self._list)
        inner.addWidget(self._scroll, 1)

        # ---- 底部输入框 ----
        self._edit = QLineEdit()
        self._edit.setPlaceholderText('输入消息，回车发送')
        self._edit.setStyleSheet(
            f'border: 1px solid {theme.CARD_BORDER}; border-radius: 6px; '
            f'font-size: 12px; padding: 4px; background: {theme.CARD}; color: {theme.TEXT};')
        self._edit.returnPressed.connect(self._on_return)
        inner.addWidget(self._edit)

    # ---------- 对外接口 ----------

    def clear(self):
        """删除所有消息行（底部弹簧保留）"""
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def append_history(self, messages):
        """追加历史（服务器返回新→旧）：微信式时序 —— 旧的在上、新的在下。

        服务器给的是新→旧，所以反着插：先插最旧的，最后插最新的，
        视觉上最新一条落在列表底部；插完滚到底部定位到最新。
        """
        if not messages:
            self._list_layout.insertWidget(0, self._make_placeholder())
            return
        for m in chronological(messages):
            row = self._make_bubble(
                m.get('sender', ''), m.get('content', ''), m.get('timestamp'))
            # 插在底部弹簧之前 = 视觉上的列表末尾
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        self._scroll_to_bottom()

    def append_message(self, sender, content, timestamp=None):
        """实时消息追加到底部（从底部弹出），并滚到最新"""
        self._list_layout.insertWidget(
            self._list_layout.count() - 1,
            self._make_bubble(sender, content, timestamp))
        self._scroll_to_bottom()

    def focus_edit(self):
        """打开后把焦点交给输入框，可立即打字"""
        self._edit.setFocus()

    def anchor_to(self, x, y):
        """按锚点定位（叠加用户拖标题条拖出来的偏移）——PetWindow 跟随用"""
        dx, dy = self._user_offset
        self.move(x + dx, y + dy)

    def user_offset(self):
        """当前记住的相对偏移 (dx, dy)"""
        return self._user_offset

    def reset_offset(self):
        """清掉偏移，回到「正好在锚点上」"""
        self._user_offset = (0, 0)

    # ---------- 内部 ----------

    def _on_return(self):
        """回车：非空则发信号，然后清空输入框"""
        text = self._edit.text().strip()
        if text:
            self.sig_send.emit(text)
        self._edit.clear()

    def _make_placeholder(self):
        lab = QLabel('（暂无聊天记录）')
        lab.setStyleSheet(f'color: {theme.TEXT_DIM}; font-size: 12px; border: none;')
        lab.setAlignment(Qt.AlignCenter)
        return lab

    def _make_bubble(self, sender, content, timestamp):
        """一行消息：布布左棕色气泡 / 我右白色气泡（时间+名字小字在气泡内顶部）"""
        is_me = sender == self._identity
        who = '我' if is_me else sender
        head = ''
        if timestamp:
            t = datetime.fromtimestamp(timestamp).strftime('%H:%M')
            head_color = theme.TEXT_DIM if is_me else '#FFE8D6'
            head = (f'<span style="font-size:10px; color:{head_color};">'
                    f'{t} {escape(who)}</span><br>')
        bubble = QLabel(f'{head}{escape(content)}')
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(BUBBLE_MAX_W)
        bubble.setStyleSheet(BUBBLE_ME if is_me else BUBBLE_PEER)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        if is_me:
            h.addStretch()
            h.addWidget(bubble)
        else:
            h.addWidget(bubble)
            h.addStretch()
        return row

    def _scroll_to_bottom(self):
        """滚到底部看最新一条。

        滚动条的 maximum 要等下一次布局pass才更新，所以延迟一拍再滚；
        否则拿到的是旧 maximum，消息多时会停在半路。
        """
        QTimer.singleShot(0, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self):
        bar = self._scroll.verticalScrollBar()
        # 先让新消息行的高度和内容尺寸算出来，maximum 才是新值；
        # 直接读会拿到布局更新前的旧 maximum，消息一多就滚不到位（停在半路甚至不动）
        self._list_layout.activate()
        self._list.adjustSize()
        bar.setValue(bar.maximum())

    def showEvent(self, event):
        """每次打开都定位到最新消息（微信式）"""
        super().showEvent(event)
        self._scroll_to_bottom()

    # ---------- 标题条拖动 ----------

    def eventFilter(self, obj, event):
        if obj is self._title:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._dragging = True
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft())
                self._drag_start_pos = self.pos()
            elif event.type() == QEvent.MouseMove and self._dragging:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
            elif event.type() == QEvent.MouseButtonRelease and self._dragging:
                self._dragging = False
                moved = self.pos() - self._drag_start_pos
                self._user_offset = (self._user_offset[0] + moved.x(),
                                     self._user_offset[1] + moved.y())
        return super().eventFilter(obj, event)
