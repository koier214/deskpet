"""使用统计窗 —— 只读展示陪伴时长：今天 / 本次 / 最近 7 天柱状图 / 累计

标准窗口（照 history_window.py 的形状）。纯视图：打开时从 UsageService 拉一次
数据，窗口开着时每 60 秒重拉；不持有、不修改任何数据。
柱状图用 paintEvent 手画，零依赖（不引 matplotlib）。
"""
from datetime import date, datetime, timedelta

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from logic.usage_service import date_key, fmt_duration

WIN_W, WIN_H = 340, 420
BAR_COLOR = '#B08968'      # 与聊天气泡同色系
EMPTY_COLOR = '#E8DFD6'
WEEKDAY_NAMES = ('周一', '周二', '周三', '周四', '周五', '周六', '周日')


def _short_duration(total_s):
    """柱顶短标注：45秒 / 12分 / 3.2小时"""
    total_s = max(0.0, float(total_s))
    if total_s < 60:
        return f'{int(total_s)}秒'
    if total_s < 3600:
        return f'{int(total_s // 60)}分'
    hours = total_s / 3600
    text = f'{hours:.1f}'.rstrip('0').rstrip('.')
    return f'{text}小时'


class WeekBars(QWidget):
    """最近 7 天陪伴时长柱状图（手画，约 50 行）"""

    def __init__(self):
        super().__init__()
        self._items = []   # [(label, seconds)] 旧→新
        self.setMinimumHeight(130)

    def set_items(self, items):
        self._items = list(items)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self._items:
            return

        width, height = self.width(), self.height()
        value_h, label_h = 16, 18
        plot_h = height - value_h - label_h - 4
        slot = width / len(self._items)
        bar_w = max(8, int(slot * 0.5))
        max_v = max(v for _, v in self._items)

        for i, (label, seconds) in enumerate(self._items):
            cx = slot * i + slot / 2
            if max_v > 0 and seconds > 0:
                bar_h = max(2, int(plot_h * seconds / max_v))
            else:
                bar_h = 2
            x = int(cx - bar_w / 2)
            y = value_h + (plot_h - bar_h)
            color = BAR_COLOR if seconds > 0 else EMPTY_COLOR
            painter.fillRect(x, y, bar_w, bar_h, QColor(color))

            if seconds > 0:
                painter.drawText(
                    QRectF(cx - slot / 2, y - value_h, slot, value_h),
                    Qt.AlignCenter, _short_duration(seconds))
            painter.drawText(
                QRectF(cx - slot / 2, value_h + plot_h + 2, slot, label_h),
                Qt.AlignCenter, label)


class UsageWidget(QWidget):
    """使用统计内容组件（可嵌入）：今天 / 本次 / 最近 7 天柱状图 / 累计

    菜单面板的标签页与独立统计窗都只是它的壳。打开时拉一次数据，
    可见期间每 60 秒重拉。
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        hint = QLabel('统计只在本地；桌宠开着的时间都算陪伴')
        hint.setStyleSheet('font-size: 11px; color: #999;')
        layout.addWidget(hint)

        self._today_label = QLabel()
        self._today_label.setStyleSheet('font-size: 14px; font-weight: bold;')
        layout.addWidget(self._today_label)

        self._session_label = QLabel()
        self._session_label.setStyleSheet('font-size: 12px; color: #666;')
        layout.addWidget(self._session_label)

        week_title = QLabel('最近 7 天')
        week_title.setStyleSheet('font-size: 12px; color: #666; margin-top: 6px;')
        layout.addWidget(week_title)

        self._bars = WeekBars()
        layout.addWidget(self._bars)

        self._total_label = QLabel()
        self._total_label.setStyleSheet('font-size: 12px; color: #666;')
        layout.addWidget(self._total_label)

        layout.addStretch(1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(60_000)
        self._refresh_timer.timeout.connect(self.refresh)

    # ---------- 对外接口 ----------

    def refresh(self):
        service = self._service
        self._today_label.setText(f'今天：已陪伴 {fmt_duration(service.today())}')
        self._session_label.setText(
            f'本次：已陪伴 {fmt_duration(service.current_session_seconds())}')

        daily = service.daily()
        today = date.today()
        items = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            key = day.strftime('%Y-%m-%d')
            seconds = float(daily.get(key, {}).get('runtime_s', 0.0))
            items.append((WEEKDAY_NAMES[day.weekday()], seconds))
        self._bars.set_items(items)

        total = sum(float(v.get('runtime_s', 0.0)) for v in daily.values())
        first_use = service.first_use_ts()
        first_day = (datetime.fromtimestamp(first_use).date()
                     if first_use else today)
        days = (today - first_day).days + 1
        self._total_label.setText(
            f'自 {first_day.strftime("%Y-%m-%d")} 起，'
            f'共陪伴 {fmt_duration(total)} / {days} 天')

    # ---------- 生命周期 ----------

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self._refresh_timer.start()

    def hideEvent(self, event):
        self._refresh_timer.stop()
        super().hideEvent(event)


class UsageWindow(QWidget):
    """独立使用统计窗（UsageWidget 的薄壳）"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.setWindowTitle('一二布布 使用统计')
        self.resize(WIN_W, WIN_H)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(UsageWidget(service, self))
