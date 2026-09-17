"""待办气泡 —— 悬浮在一二头顶的任务列表，由 TaskService 信号驱动增量刷新

气泡只是视图：不读盘、不写盘、不持有数据。原先每次刷新都 deleteLater 掉全部行再
load_data() 重建，计时器常驻后这变成每秒一次的整窗闪烁；现在每秒只改一个
timer_label 的文本，只有结构真的变了（增/删/换区）才动布局。

两个区域（2026-09-11 按用户手绘稿重排）：
- 待办：**未完成 且（归属今天 或 未安排）** 的任务，和之前一致
- 已完成：**今天完成** 的任务（以 done_at 时间戳为准）；没有 done_at 的旧数据
  不进已完成区，几天前完成的任务不会一直挂头顶。勾选完成的行会从待办区
  挪到已完成区；已完成行右键可「恢复待办 / 删除任务」

两个滚动区横向滚动条永久关闭：文字过长自动省略号（elide），不撑宽行；
完整文字放在 tooltip 里，鼠标悬停可看全。
"""
from datetime import date, datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QMenu,
    QSizePolicy,
)

# 视觉常量集中在 ui/theme.py（暖色系），这里只引用不改含义
from ui import theme

BUBBLE_W = 230   # 固定宽度
BUBBLE_H = 300   # 固定高度（2026-09-11：220→300，给已完成区腾地方）
ROW_H = 32       # 待办行固定高度
DONE_ROW_H = 24  # 已完成行固定高度（更紧凑）

# 文字列可用宽度 = 气泡内宽 208 - 行边距 - 间隔 - 各固定列
# 待办行：208 - 8 - 12(三个间隔) - 14(标记) - 42(倒计时) - 40(状态) = 92
TEXT_MAX_W_TODO = 92
# 已完成行：208 - 8 - 4(一个间隔) - 14(标记) = 182
TEXT_MAX_W_DONE = 182

# 状态标签配色（与面板保持一致；语义色不变，圆角/中性灰走主题）
STATUS_STYLE = {
    'done': ('完成', f'background-color: #E8F5E9; color: {theme.DONE_GREEN}; '
                    'font-size: 11px; font-weight: bold; border: none; border-radius: 6px;'),
    'in_progress': ('进行中', f'background-color: {theme.RUN_RED_BG}; color: {theme.RUN_RED}; '
                             'font-size: 11px; font-weight: bold; border: none; border-radius: 6px;'),
    'paused': ('暂停中', f'background-color: {theme.PAUSE_ORANGE_BG}; color: {theme.PAUSE_ORANGE}; '
                        'font-size: 11px; font-weight: bold; border: none; border-radius: 6px;'),
    'todo': ('待做', f'background-color: {theme.NEUTRAL_BG}; color: {theme.NEUTRAL_TEXT}; '
                    'font-size: 11px; border: none; border-radius: 6px;'),
}

# 倒计时底色：跟状态标签同一套色系，扫一眼就知道这条在跑还是暂停
_TIMER_BASE = 'border: none; font-size: 11px; border-radius: 6px;'
TIMER_STYLE = {
    'zero': _TIMER_BASE + ' background: #FFCDD2; color: #B71C1C; font-weight: bold;',
    'in_progress': _TIMER_BASE + f' background: {theme.RUN_RED_BG}; color: {theme.RUN_RED};',
    'paused': _TIMER_BASE + f' background: {theme.PAUSE_ORANGE_BG}; color: {theme.PAUSE_ORANGE};',
    'todo': _TIMER_BASE + f' background: {theme.NEUTRAL_BG}; color: {theme.NEUTRAL_TEXT};',
}


class TaskBubble(QWidget):
    """头顶气泡：待办（今天+未安排的未完成）+ 已完成（今天完成的），TaskService 信号驱动"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self.pet_name = service.pet_name
        self._rows = {}          # task_id -> {'row','marker','text','timer','status','section','container'}

        # 无边框、置顶、不在任务栏
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(BUBBLE_W, BUBBLE_H)

        # 气泡本体：和聊天白色消息卡同一张脸（theme.CARD_SPEC['panel']）
        self._bubble = QWidget(self)
        self._bubble.setObjectName('bubble')
        self._bubble.setStyleSheet(theme.surface_qss('panel', 'bubble'))
        self._bubble.setFixedSize(BUBBLE_W, BUBBLE_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._bubble)

        layout = QVBoxLayout(self._bubble)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # 标题行
        title = QLabel('📋 待办')
        title.setFixedHeight(24)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet(
            f'font-weight: bold; font-size: 12px; border: none; color: {theme.ACCENT_DARK};')
        layout.addWidget(title)
        self._title = title

        # ---- 待办滚动区 ----
        self._scroll = self._make_scroll()
        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet('background: transparent;')
        self._task_container = QVBoxLayout(self._scroll_content)
        self._task_container.setSpacing(2)
        self._task_container.setContentsMargins(0, 0, 0, 0)

        # 空态常驻，靠 setVisible 切换 —— 增量更新下不能再靠全量重建来插拔它
        self._empty = QLabel('暂无待办')
        self._empty.setFixedHeight(ROW_H)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(f'color: {theme.TEXT_DIM}; border: none; font-size: 12px;')
        self._task_container.addWidget(self._empty)

        self._task_container.addStretch()
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 3)

        # ---- 已完成区（没内容时整块隐藏，待办区吃满高度）----
        self._done_header = QLabel('✓ 已完成（0）')
        self._done_header.setFixedHeight(18)
        self._done_header.setStyleSheet(
            f'color: {theme.DONE_GREEN}; border: none; font-size: 11px; font-weight: bold;')
        layout.addWidget(self._done_header)

        self._done_scroll = self._make_scroll()
        self._done_content = QWidget()
        self._done_content.setStyleSheet('background: transparent;')
        self._done_container = QVBoxLayout(self._done_content)
        self._done_container.setSpacing(2)
        self._done_container.setContentsMargins(0, 0, 0, 0)
        self._done_container.addStretch()
        self._done_scroll.setWidget(self._done_content)
        layout.addWidget(self._done_scroll, 2)

        self._update_sections_visible()

        service.sig_task_added.connect(self._on_added)
        service.sig_task_removed.connect(self._on_removed)
        service.sig_task_updated.connect(self._on_updated)
        service.sig_tick.connect(self._on_tick)

    @staticmethod
    def _make_scroll():
        """滚动区：透明无边框，横向滚动条永久关（文字靠省略号收）"""
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea { border: none; background: transparent; }')
        return scroll

    # ==================== 筛选 ====================

    def _section_of(self, task):
        """这条任务该进哪个区：'todo' / 'done' / None（不上气泡）"""
        if task['done']:
            return 'done' if _done_today(task) else None
        due = task.get('due_date')
        if due is None or due == date.today().strftime('%Y-%m-%d'):
            return 'todo'
        return None

    # ==================== 信号槽 ====================

    def _on_added(self, task_id):
        """新任务插到对应区底部弹簧之前，保持与 tasks() 相同的顺序"""
        if task_id in self._rows:
            return
        task = self._service.task(task_id)
        if task is None:
            return
        section = self._section_of(task)
        if section is None:
            return
        self._insert_row(task, section)
        self._update_sections_visible()

    def _on_removed(self, task_id):
        refs = self._rows.pop(task_id, None)
        if refs is None:
            return
        refs['container'].removeWidget(refs['row'])
        refs['row'].deleteLater()
        self._update_sections_visible()

    def _on_updated(self, task_id):
        """done / text / timer / status / due_date 任一变化：
        区没变 → 原地重刷；换区 → 拆旧行建新行（两种行的控件不一样）；
        移出气泡 → 撤行；移入气泡 → 建行"""
        task = self._service.task(task_id)
        if task is None:
            return
        refs = self._rows.get(task_id)
        section = self._section_of(task)
        old = refs['section'] if refs is not None else None
        if section == old and refs is not None:
            self._apply_row(task, refs)
            return
        if refs is not None:
            refs['container'].removeWidget(refs['row'])
            refs['row'].deleteLater()
            del self._rows[task_id]
        if section is not None:
            self._insert_row(task, section)
        self._update_sections_visible()

    def _on_tick(self, task_id, remaining_s):
        """高频热路径：只改倒计时文本和底色，绝不重算布局、绝不读盘"""
        refs = self._rows.get(task_id)
        if refs is None or refs['timer'] is None:
            return
        task = self._service.task(task_id)
        if task is None:
            return
        refs['timer'].setText(self._format_timer(task['timer_total_s'], remaining_s))
        refs['timer'].setStyleSheet(_timer_style(task, remaining_s))

    # ==================== 全量刷新 ====================

    def reload_all(self):
        """按内存数据重建所有行（打开气泡时用）"""
        for refs in self._rows.values():
            refs['container'].removeWidget(refs['row'])
            refs['row'].deleteLater()
        self._rows.clear()

        for task in self._service.tasks():
            section = self._section_of(task)
            if section is None:
                continue
            self._insert_row(task, section)
        self._update_sections_visible()

    # 兼容旧调用名
    refresh = reload_all

    def _update_sections_visible(self):
        """待办空态、已完成区显隐、已完成计数，三处一起对齐"""
        n_todo = sum(1 for r in self._rows.values() if r['section'] == 'todo')
        n_done = sum(1 for r in self._rows.values() if r['section'] == 'done')
        self._empty.setVisible(n_todo == 0)
        has_done = n_done > 0
        self._done_header.setVisible(has_done)
        self._done_scroll.setVisible(has_done)
        if has_done:
            self._done_header.setText(f'✓ 已完成（{n_done}）')

    # ==================== 行构建 ====================

    def _insert_row(self, task, section):
        container = self._task_container if section == 'todo' else self._done_container
        container.insertWidget(container.count() - 1, self._build_row(task, section))

    def _build_row(self, task, section):
        """构建单行并把控件引用登记到 self._rows，供后续增量更新"""
        row = QWidget()
        row.setStyleSheet('border: none;')
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(4)

        marker = QLabel()
        marker.setFixedWidth(14)
        marker.setAlignment(Qt.AlignCenter)
        layout.addWidget(marker)

        text = QLabel()
        text.setWordWrap(False)
        # 宽度交给布局压缩：哪怕省略算漏了也不会把行撑出横向滚动条
        text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(text, 1)

        if section == 'todo':
            row.setFixedHeight(ROW_H)
            # 无条件创建，没设时长时 hide —— 否则"设时"把 0 改成 >0 时这行没有
            # label 可更新，只能整行重建
            timer = QLabel()
            timer.setFixedWidth(42)
            timer.setFixedHeight(18)
            timer.setAlignment(Qt.AlignCenter)
            layout.addWidget(timer)

            status = QLabel()
            status.setFixedWidth(40)
            status.setAlignment(Qt.AlignCenter)
            layout.addWidget(status)
        else:
            row.setFixedHeight(DONE_ROW_H)
            row.setProperty('task_id', task['id'])
            row.installEventFilter(self)   # 右键 → 恢复待办 / 删除任务
            timer = None
            status = None

        refs = {'row': row, 'marker': marker, 'text': text, 'timer': timer,
                'status': status, 'section': section,
                'container': self._task_container if section == 'todo' else self._done_container}
        self._rows[task['id']] = refs
        self._apply_row(task, refs)
        return row

    def _apply_row(self, task, refs):
        """把一条任务的当前状态刷到已有控件上（不新建 widget）"""
        done = task['done']

        refs['marker'].setText('✓' if done else '•')
        refs['marker'].setStyleSheet(
            f'color: {theme.DONE_GREEN}; border: none; font-size: 12px; font-weight: bold;'
            if done else
            f'color: {theme.NEUTRAL_TEXT}; border: none; font-size: 12px;'
        )

        label = refs['text']
        font = label.font()
        font.setUnderline(done)
        label.setFont(font)
        label.setStyleSheet(
            f'color: {theme.TEXT_DIM}; border: none; font-size: 12px;' if done
            else f'color: {theme.TEXT}; border: none; font-size: 12px;'
        )
        max_w = TEXT_MAX_W_TODO if refs['section'] == 'todo' else TEXT_MAX_W_DONE
        self._elide(label, task['text'], max_w)

        if refs['timer'] is not None:
            total = task.get('timer_total_s', 0)
            remaining = task.get('timer_remaining_s', 0)
            refs['timer'].setVisible(total > 0)
            if total > 0:
                refs['timer'].setText(self._format_timer(total, remaining))
                refs['timer'].setStyleSheet(_timer_style(task, remaining))

        if refs['status'] is not None:
            text, style = STATUS_STYLE.get(task.get('status', 'todo'), STATUS_STYLE['todo'])
            refs['status'].setText(text)
            refs['status'].setStyleSheet(style)

    @staticmethod
    def _elide(label, full_text, max_w):
        """文字过宽就省略号收尾；完整文字放 tooltip，悬停可看全"""
        elided = label.fontMetrics().elidedText(full_text, Qt.ElideRight, max_w)
        label.setText(elided)
        label.setToolTip(full_text if elided != full_text else '')

    # ==================== 已完成行右键菜单 ====================

    def eventFilter(self, obj, event):
        if event.type() == QEvent.ContextMenu:
            task_id = obj.property('task_id')
            if task_id:
                self._show_done_menu(task_id)
                return True
        return super().eventFilter(obj, event)

    def _show_done_menu(self, task_id):
        menu = QMenu(self)
        restore_action = menu.addAction('恢复待办')
        delete_action = menu.addAction('删除任务')
        chosen = menu.exec_(QCursor.pos())
        if chosen == restore_action:
            self._service.set_done(task_id, False)
        elif chosen == delete_action:
            self._service.remove_task(task_id)

    @staticmethod
    def _format_timer(total_s, remaining_s):
        m, s = divmod(max(0, int(remaining_s)), 60)
        return f'{m:02d}:{s:02d}'

    # ==================== 生命周期 ====================

    def showEvent(self, event):
        """每次显示时按内存数据重刷一遍，保证与面板一致"""
        super().showEvent(event)
        self.reload_all()


def _done_today(task):
    """今天完成？以 done_at 为准；旧数据没有 done_at 不算（不挂头顶）"""
    ts = task.get('done_at')
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False
    return datetime.fromtimestamp(ts).date() == date.today()


def _timer_style(task, remaining_s):
    """倒计时底色：归零红底 > 状态色系"""
    if remaining_s <= 0:
        return TIMER_STYLE['zero']
    return TIMER_STYLE.get(task.get('status', 'todo'), TIMER_STYLE['todo'])
