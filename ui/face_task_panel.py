"""一二大脸异形面板 —— 用 PNG 图片做自定义形状的任务窗口"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QBitmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QScrollArea, QFrame, QApplication,
)

from ui.task_panel import TaskPanel

# 素材原始尺寸和坐标
IMG_W, IMG_H = 787, 930
FACE_IMG = "static/images/yier_panel.png"

LEFT_EAR = (66, 20, 135, 101)
RIGHT_EAR = (650, 21, 717, 98)
BOW = (154, 642, 606, 664)
CONTENT_RECT = (131, 141, 638, 578)

MAX_HEIGHT_RATIO = 0.85   # 最大占屏幕高度的比例


class FaceTaskPanel(TaskPanel):
    """用一二大脸图片做异形窗口的任务面板"""

    def _init_ui(self):
        """覆盖父类 _init_ui：异形窗口 + 透明按钮 + 脸部内容区"""
        # ---- 根据屏幕高度计算缩放比例 ----
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        self._scale = min(MAX_HEIGHT_RATIO * screen_h / IMG_H, 1.0)
        self._scale = max(self._scale, 0.35)  # 最小不低于 35%

        w = int(IMG_W * self._scale)
        h = int(IMG_H * self._scale)

        self.setWindowTitle('一二的待办')
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(w, h)

        # ---- 背景图片（缩放后） ----
        pix = QPixmap(FACE_IMG).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        bg = QLabel(self)
        bg.setPixmap(pix)
        bg.setFixedSize(w, h)

        # ---- 窗口遮罩 ----
        mask = pix.toImage().createAlphaMask()
        self.setMask(QBitmap.fromImage(mask))

        # ---- 三个透明按钮（按比例缩放坐标） ----
        self._ear_left_btn = self._make_invis_btn(LEFT_EAR)
        self._ear_left_btn.clicked.connect(self.hide)

        self._ear_right_btn = self._make_invis_btn(RIGHT_EAR)
        self._ear_right_btn.clicked.connect(self.close)

        self._bow_btn = self._make_invis_btn(BOW)
        self._bow_btn.clicked.connect(self.showMinimized)

        # ---- 脸部内容容器（按比例缩放） ----
        x1, y1, x2, y2 = CONTENT_RECT
        content = QWidget(self)
        content.setGeometry(
            int(x1 * self._scale), int(y1 * self._scale),
            int((x2 - x1) * self._scale), int((y2 - y1) * self._scale),
        )
        content.setStyleSheet('background: rgba(255,255,255,0.88); border-radius: 8px;')

        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(10, 8, 10, 8)

        # 输入行
        input_row = QHBoxLayout()
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText('输入新任务，回车添加...')
        self._task_input.returnPressed.connect(self._on_add_task)
        input_row.addWidget(self._task_input)

        add_btn = QPushButton('添加')
        add_btn.clicked.connect(self._on_add_task)
        input_row.addWidget(add_btn)
        content_layout.addLayout(input_row)

        # 滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet('background: transparent;')
        self._task_list_layout = QVBoxLayout(self._scroll_content)
        self._task_list_layout.setSpacing(4)
        self._task_list_layout.setContentsMargins(0, 0, 0, 0)
        self._task_list_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)

        content_layout.addWidget(self._scroll, 1)

        # 居中显示
        self._center_on_screen()

    def _make_invis_btn(self, rect):
        """创建透明按钮，坐标按当前缩放比例计算"""
        x1, y1, x2, y2 = rect
        bw = int((x2 - x1) * self._scale)
        bh = int((y2 - y1) * self._scale)
        btn = QPushButton(self)
        btn.setGeometry(int(x1 * self._scale), int(y1 * self._scale), bw, bh)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.25);
                border-radius: 5px;
            }
        """)
        return btn

    # ==================== 脸部拖拽 ====================

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.pos()
        event.accept()

    def mouseMoveEvent(self, event):
        if hasattr(self, '_drag_offset'):
            self.move(event.globalPos() - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self, '_drag_offset'):
            del self._drag_offset
        event.accept()
