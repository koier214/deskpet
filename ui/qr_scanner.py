"""屏幕二维码框选与结果窗口；业务状态及倒计时统一交给 QrScanService。"""
import math

from PySide6.QtCore import QObject, QPoint, QRect, QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from logic.qr_service import QrScanService
from ui import theme


def crop_screen_image(image, display_size, selection):
    """逻辑坐标映射到截图物理像素，兼容副屏、负坐标与不同缩放比例。"""
    bounds = QRect(QPoint(), display_size)
    rect = selection.normalized().intersected(bounds)
    if image.isNull() or rect.isEmpty() or bounds.isEmpty():
        return QImage()
    sx = image.width() / bounds.width()
    sy = image.height() / bounds.height()
    left, top = math.floor(rect.x() * sx), math.floor(rect.y() * sy)
    right = math.ceil((rect.x() + rect.width()) * sx)
    bottom = math.ceil((rect.y() + rect.height()) * sy)
    result = image.copy(left, top, right - left, bottom - top)
    result.setDevicePixelRatio(1.0)
    return result


class ScreenRegionSelector(QWidget):
    """每块屏幕单独覆盖，截取在覆盖层出现之前完成，避免把遮罩扫进去。"""

    sig_selected = Signal(object)
    sig_cancelled = Signal()

    def __init__(self, geometry, snapshot):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('框选二维码')
        self.setGeometry(geometry)
        self.setCursor(Qt.CrossCursor)
        self._snapshot = snapshot
        self._start = None
        self._selection = QRect()
        self._hint = QLabel('拖动鼠标框选完整二维码  ·  Esc / 右键取消', self)
        self._hint.setStyleSheet(theme.QR_HINT_QSS)
        self._hint.adjustSize()
        self._hint.move(max(8, (self.width() - self._hint.width()) // 2), 24)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._snapshot)
        painter.fillRect(self.rect(), QColor(theme.QR_MASK))
        if not self._selection.isEmpty():
            # 选区重画原图，让二维码保持截图时的清晰度。
            painter.save()
            painter.setClipRect(self._selection)
            painter.drawPixmap(self.rect(), self._snapshot)
            painter.restore()
            painter.setPen(QPen(QColor(theme.ACCENT), 2))
            painter.drawRect(self._selection)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.sig_cancelled.emit()
        elif event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._selection = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._start is None:
            return
        self._selection = QRect(self._start, event.position().toPoint()).normalized()
        self._start = None
        if self._selection.width() < 8 or self._selection.height() < 8:
            self._selection = QRect()
            self.update()
            return
        self.sig_selected.emit(crop_screen_image(
            self._snapshot.toImage(), self.size(), self._selection))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.sig_cancelled.emit()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._snapshot = type(self._snapshot)()
        self.sig_cancelled.emit()
        super().closeEvent(event)


class QrResultDialog(QDialog):
    sig_retry = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint)
        self._service = service
        self._listed_results = None
        self.setWindowTitle('二维码扫描')
        self.setObjectName('qrResult')
        self.setStyleSheet(theme.QR_DIALOG_QSS)
        self.resize(520, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self._title = QLabel('二维码扫描结果')
        self._title.setObjectName('qrTitle')
        layout.addWidget(self._title)
        self._choices = QComboBox()
        self._choices.setPlaceholderText('请选择一个二维码')
        self._choices.currentIndexChanged.connect(self._on_choice)
        layout.addWidget(self._choices)
        self._content = QPlainTextEdit()
        self._content.setReadOnly(True)
        self._content.setMaximumHeight(130)
        layout.addWidget(self._content)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.PlainText)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._retry_btn = QPushButton('重新扫描')
        self._copy_btn = QPushButton('复制网址')
        self._cancel_btn = QPushButton('取消跳转')
        self._open_btn = QPushButton('立即跳转')
        self._open_btn.setObjectName('qrOpen')
        for button in (self._retry_btn, self._copy_btn, self._cancel_btn, self._open_btn):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._retry_btn.clicked.connect(self.sig_retry)
        self._copy_btn.clicked.connect(self._copy)
        self._cancel_btn.clicked.connect(service.cancel_auto_open)
        self._open_btn.clicked.connect(service.open_now)
        service.sig_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        service = self._service
        if service.results != self._listed_results:
            with QSignalBlocker(self._choices):
                self._choices.clear()
                for index, text in enumerate(service.results):
                    summary = ' '.join(text.split())
                    self._choices.addItem(f'{index + 1}. {summary[:70]}')
                self._choices.setCurrentIndex(service.selected_index)
            self._listed_results = service.results
        self._choices.setVisible(len(service.results) > 1)
        text = service.url or service.selected_text
        if self._content.toPlainText() != text:
            self._content.setPlainText(text)
        self._content.setVisible(bool(text))
        self._title.setText('识别到的网址' if service.url else '二维码扫描结果')
        self._status.setText(f'{service.remaining_seconds} 秒后自动跳转，可取消或立即跳转。'
                             if service.remaining_seconds else service.message)
        self._copy_btn.setText('复制网址' if service.url else '复制内容')
        self._copy_btn.setEnabled(bool(text))
        self._cancel_btn.setEnabled(service.remaining_seconds > 0)
        self._open_btn.setEnabled(bool(service.url) and service.state == 'result')

    def _on_choice(self, index):
        self._service.select_result(index)
        if self.isVisible():
            self._service.start_countdown()

    def _copy(self):
        text = self._service.copy_result()
        if text:
            QApplication.clipboard().setText(text)

    def present(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(520, area.width()), min(320, area.height()))
            self.move(area.center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()
        self._cancel_btn.setFocus()
        self._service.start_countdown()

    def done(self, result):
        self._service.cancel_auto_open()
        super().done(result)

    def hideEvent(self, event):
        self._service.cancel_auto_open()
        super().hideEvent(event)


class QrScanner(QObject):
    """协调一次扫描；全局热键重复触发、关闭与退出都会停止旧倒计时。"""

    def __init__(self, parent=None, capture_fn=None, opener=None):
        super().__init__(parent)
        self.service = QrScanService(self)
        self.service.sig_open_url.connect(self._open_url)
        self._parent_widget = parent
        self._capture = capture_fn or self._capture_screens
        self._opener = opener or QDesktopServices.openUrl
        self._overlays = []
        self._dialog = None
        # 等菜单/旧结果窗隐藏后再截屏，这是一次性延迟，不轮询屏幕。
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.setInterval(150)
        self._capture_timer.timeout.connect(self._show_selectors)

    @staticmethod
    def _capture_screens():
        return [(screen.geometry(), screen.grabWindow(0)) for screen in QApplication.screens()]

    def toggle(self):
        if self._overlays or self._capture_timer.isActive():
            self.shutdown()
            return
        self.start()

    def start(self):
        self.shutdown()
        self.service.begin_scan()
        self._capture_timer.start()

    def _show_selectors(self):
        try:
            captures = self._capture()
            if not captures or any(snapshot.isNull() for _, snapshot in captures):
                raise RuntimeError('截图为空')
        except Exception:
            self.service.fail('无法截取屏幕，请检查系统录屏权限后重新扫描。')
            self._show_result()
            return
        # 先截完所有屏幕，再同时显示覆盖层，避免副屏截图里出现覆盖层。
        for geometry, snapshot in captures:
            overlay = ScreenRegionSelector(geometry, snapshot)
            overlay.sig_selected.connect(self._on_selected)
            overlay.sig_cancelled.connect(self.shutdown)
            self._overlays.append(overlay)
        for overlay in self._overlays:
            overlay.show()
            overlay.raise_()
        active = next((overlay for overlay in self._overlays
                       if overlay.geometry().contains(QCursor.pos())), self._overlays[0])
        active.activateWindow()
        active.setFocus()

    def _close_selectors(self):
        overlays, self._overlays = self._overlays, []
        for overlay in overlays:
            overlay.blockSignals(True)
            overlay.close()
            overlay.deleteLater()

    def _on_selected(self, image):
        self._close_selectors()
        self.service.scan_image(image)
        self._show_result()

    def _show_result(self):
        if self._dialog is None:
            self._dialog = QrResultDialog(self.service, self._parent_widget)
            self._dialog.sig_retry.connect(self.start)
        self._dialog.present()

    def _open_url(self, url):
        try:
            success = bool(self._opener(QUrl(url)))
        except Exception:
            success = False
        self.service.report_open_result(success)

    def shutdown(self):
        self._capture_timer.stop()
        self.service.reset()
        self._close_selectors()
        if self._dialog is not None:
            self._dialog.hide()
