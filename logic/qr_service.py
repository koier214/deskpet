"""二维码识别与跳转状态：本机解码，倒计时由服务持有，不依赖具体窗口。"""
import math
import time
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QObject, QTimer, Qt, Signal


def normalize_web_url(text):
    """只接受 HTTP(S) 网址；www. 开头补 https，其他内容保留供复制。"""
    text = text.strip()
    if not text or any(ord(char) < 32 or ord(char) == 127 or char.isspace()
                       for char in text):
        return ''
    if '\\' in text:
        return ''
    if text.lower().startswith('www.'):
        text = 'https://' + text
    try:
        parts = urlsplit(text)
        if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
            return ''
        # 不让带账号密码的地址隐藏真实访问域名，也不触发程序或文件协议。
        if parts.username is not None or parts.password is not None:
            return ''
        host = parts.hostname
        if ':' not in host:
            host = host.encode('idna').decode('ascii')
            if any(not label or len(label) > 63
                   or label.startswith('-') or label.endswith('-')
                   or any(not (c.isascii() and (c.isalnum() or c == '-')) for c in label)
                   for label in host.rstrip('.').split('.')):
                return ''
        else:
            # urlsplit 已校验方括号里的 IPv6 地址。
            host = f'[{host}]'
        port = parts.port    # 非数字或越界端口会抛 ValueError。
        if port is not None:
            host += f':{port}'
        return urlunsplit((parts.scheme.lower(), host, parts.path,
                           parts.query, parts.fragment))
    except (ValueError, UnicodeError):
        return ''


def decode_qr_codes(image):
    """懒加载解码器；直接接收 QImage，不需要 numpy，也不写截图文件。"""
    import zxingcpp

    codes = zxingcpp.read_barcodes(
        image, formats=zxingcpp.BarcodeFormat.QRCode,
        text_mode=zxingcpp.TextMode.Plain)
    # 同一个码出现多次只列一次，顺序保持解码器给出的屏幕顺序。
    return list(dict.fromkeys(code.text for code in codes if code.valid and code.text))


class QrScanService(QObject):
    """持有识别结果、选择与三秒倒计时；用信号请求外部打开网址。"""

    sig_changed = Signal()
    sig_open_url = Signal(str)

    def __init__(self, parent=None, now_fn=None):
        super().__init__(parent)
        self._now = now_fn or time.monotonic
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_timeout)
        self._deadline = None
        self.results = ()
        self.selected_index = -1
        self.state = 'idle'
        self.message = ''
        self.remaining_seconds = 0

    @property
    def selected_text(self):
        if 0 <= self.selected_index < len(self.results):
            return self.results[self.selected_index]
        return ''

    @property
    def url(self):
        return normalize_web_url(self.selected_text)

    def _stop_countdown(self):
        self._timer.stop()
        self._deadline = None
        self.remaining_seconds = 0

    def reset(self):
        self._stop_countdown()
        self.results = ()
        self.selected_index = -1
        self.state = 'idle'
        self.message = ''
        self.sig_changed.emit()

    def begin_scan(self):
        self.reset()
        self.state = 'scanning'
        self.sig_changed.emit()

    def fail(self, message):
        self.reset()
        self.state = 'error'
        self.message = message
        self.sig_changed.emit()

    def scan_image(self, image):
        self.begin_scan()
        if image.isNull():
            self.fail('没有获取到截图，请重新框选二维码。')
            return
        try:
            results = decode_qr_codes(image)
        except ImportError:
            self.fail('缺少二维码解码库，请先运行 python -m pip install -r requirements.txt。')
            return
        except Exception:
            # 解码失败不打印截图内容或二维码原文，避免把私密链接写进日志。
            self.fail('二维码识别失败，请重新框选清晰、完整的二维码。')
            return
        if not results:
            self.fail('未识别到二维码，请框选完整二维码，并保留四周空白。')
            return
        self.results = tuple(results)
        self.state = 'result'
        self.select_result(0 if len(results) == 1 else -1)

    def select_result(self, index):
        self._stop_countdown()
        self.selected_index = index if 0 <= index < len(self.results) else -1
        self.state = 'result'
        if self.selected_index < 0:
            self.message = '识别到多个二维码，请选择要打开的那一个。'
        elif self.url:
            self.message = '识别到网址。'
        else:
            self.message = '二维码内容不是可打开的 HTTP(S) 网址，可以复制内容。'
        self.sig_changed.emit()

    def start_countdown(self):
        """视图显示结果后再计时，保证用户有完整三秒进行操作。"""
        if self.state != 'result' or not self.url:
            return
        self._stop_countdown()
        self._deadline = self._now() + 3.0
        self.remaining_seconds = 3
        self.message = ''
        self._timer.start(1000)
        self.sig_changed.emit()

    def _on_timeout(self):
        if self._deadline is None:
            return
        left = self._deadline - self._now()
        if left <= 0:
            self.open_now()
            return
        self.remaining_seconds = math.ceil(left)
        self._timer.start(max(1, min(1000, math.ceil(left * 1000))))
        self.sig_changed.emit()

    def cancel_auto_open(self):
        if self._deadline is None:
            return
        self._stop_countdown()
        self.message = '已取消自动跳转。'
        self.sig_changed.emit()

    def copy_result(self):
        """复制也取消倒计时，避免用户复制后又被自动带到浏览器。"""
        text = self.url or self.selected_text
        if text:
            self._stop_countdown()
            self.message = '网址已复制，自动跳转已取消。' if self.url else '内容已复制。'
            self.sig_changed.emit()
        return text

    def open_now(self):
        if self.state != 'result' or not self.url:
            return
        url = self.url
        self._stop_countdown()
        self.state = 'opening'
        self.message = '正在打开浏览器…'
        self.sig_changed.emit()
        self.sig_open_url.emit(url)

    def report_open_result(self, success):
        if self.state != 'opening':
            return
        self.state = 'opened' if success else 'result'
        self.message = ('已在默认浏览器中打开。' if success
                        else '未能打开浏览器，请复制网址，或点击「立即跳转」重试。')
        self.sig_changed.emit()
