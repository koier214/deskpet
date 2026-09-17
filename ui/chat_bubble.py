"""聊天气泡 —— 一二头顶的消息卡片栈：最多 3 条、旧的往上挪、淡出消失

2026-09-14 改造（对照微信气泡的读法）：
  颜色按发送方：bubu 的消息棕色卡片、yier 的消息白色卡片、
  系统提示（上线/下线/番茄钟提醒）保持原来的暖白卡片
  卡片两行：标题"来自xx的消息"加粗，正文自动换行不加粗，内容上下居中、高度自适应
  消失改成淡出（定时步进透明度，不用 QGraphicsEffect——离屏平台会卡渲染）；
  消息频繁时旧卡片往上挪，同屏最多 3 条，再多最旧的先淡出
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ui import theme

BUBBLE_W = 260      # 固定宽度（和改造前一致）
CARD_MIN_H = 46     # 单条卡片最小高度：内容只有一行时也保持手感
MAX_CARDS = 3       # 同屏最多三条
FADE_MS = 360       # 淡出总时长
FADE_STEP_MS = 30   # 淡出步进间隔

class ChatBubble(QWidget):
    """收到消息时在头顶弹出的气泡卡片栈（旧在上、新在下）"""

    sig_hidden = Signal()    # 最后一条也消失时发出（供外部恢复被暂停的待办气泡）
    sig_changed = Signal()   # 卡片增删/整体尺寸变化（供外部重新锚定位置）

    def __init__(self, parent=None):
        super().__init__(parent)

        # 窗口属性：与 TaskBubble 保持一致（无边框、置顶、不在任务栏）
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedWidth(BUBBLE_W)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._cards = []     # 旧 → 新
        self._fading = []    # 正在淡出、还没拆掉的卡片

    # ---------- 对外接口 ----------

    def show_message(self, text, duration_ms=3000):
        """系统提示（上线/下线/番茄钟等）：暖白卡片，只有正文一行"""
        self._push('notice', None, text, duration_ms)

    def show_chat(self, sender, content, duration_ms=3000):
        """聊天消息：bubu 棕色 / yier 白色；标题加粗 + 正文换行不加重"""
        kind = 'peer' if sender == 'bubu' else ('me' if sender == 'yier' else 'notice')
        self._push(kind, f'来自{sender}的消息', content, duration_ms)

    def clear(self):
        """立刻清掉所有卡片（退出时用）"""
        for card in list(self._cards) + list(self._fading):
            self._drop(card)

    # ---------- 内部 ----------

    def _push(self, kind, head, body, duration_ms):
        while len(self._cards) >= MAX_CARDS:
            self._retire(self._cards[0])       # 超三条：最旧的先淡出让位
        card = self._make_card(kind, head, body)
        self._cards.append(card)
        self._layout.addWidget(card)
        self._restack()

        timer = QTimer(card)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda c=card: self._retire(c))
        timer.start(duration_ms)
        card.life_timer = timer

        self.show()
        self.raise_()

    def _make_card(self, kind, head, body):
        card = QWidget()
        card.kind = kind
        card.fade_timer = None
        card.life_timer = None
        card.setObjectName('card')
        card.setStyleSheet(theme.card_qss(kind, 1.0))
        card.setMinimumHeight(CARD_MIN_H)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        lay.setAlignment(Qt.AlignVCenter)      # 内容少时在卡片里上下居中

        if head:
            head_lab = QLabel(head)
            head_lab.setObjectName('head')
            head_lab.setWordWrap(True)
            lay.addWidget(head_lab)

        body_lab = QLabel(body)
        body_lab.setObjectName('body')
        body_lab.setWordWrap(True)
        lay.addWidget(body_lab)
        return card

    def _retire(self, card):
        """到点/超员：立刻移出活跃列表并开始淡出，淡完才真正拆 widget。

        移出是同步的，所以 _push 的超员循环不会等淡出而死循环；
        淡出期间卡片还占着位置，视觉上就是旧消息慢慢让位。
        """
        if card not in self._cards:
            return
        self._cards.remove(card)
        self._fading.append(card)
        if card.life_timer is not None:
            card.life_timer.stop()
        remaining = [FADE_MS]
        timer = QTimer(card)
        card.fade_timer = timer

        def tick():
            remaining[0] -= FADE_STEP_MS
            if remaining[0] <= 0:
                timer.stop()
                self._drop(card)
                return
            card.setStyleSheet(theme.card_qss(card.kind, remaining[0] / FADE_MS))

        timer.timeout.connect(tick)
        timer.start(FADE_STEP_MS)

    def _drop(self, card):
        if card in self._fading:
            self._fading.remove(card)
        if card in self._cards:
            self._cards.remove(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        self._restack()
        if not self._cards and not self._fading:
            self.hide()      # hideEvent 里发 sig_hidden

    def _restack(self):
        """卡片变了 → 高度跟着变（宽度固定），通知外部重新锚定"""
        self.adjustSize()
        self.sig_changed.emit()

    def hideEvent(self, event):
        """隐藏时通知外部（用于恢复被暂停的待办气泡）"""
        super().hideEvent(event)
        self.sig_hidden.emit()
