"""待办气泡 —— 悬浮在一二头顶的任务列表，由 TaskService 信号驱动增量刷新

气泡只是视图：不读盘、不写盘、不持有数据。原先每次刷新都 deleteLater 掉全部行再
load_data() 重建，计时器常驻后这变成每秒一次的整窗闪烁；现在每秒只改一个
timer_label 的文本，只有结构真的变了（增/删/换区）才动布局。

三个区域（2026-09-18 评审定稿：行首圆点分色、顺延区最多 3 条；2026-09-22 起改叫「顺延」）：
- 顺延（内部键仍是 overdue）：**有归属日期、日期早于今天、未完成** 的任务，顺延最久的排
  最前，最多显示 3 条，其余收成一行「还有 N 条，去菜单处理」；右键可「移到今天 / 删除任务」
- 待办：**未完成 且（归属今天 或 其他任务）** 的任务。行首圆点分色——
  棕 = 归属今天，暖灰 = 其他任务（气泡不显示日期，靠圆点区分归属）
- 已完成：**今天完成** 的任务（以 done_at 时间戳为准）；没有 done_at 的旧数据
  不进已完成区，几天前完成的任务不会一直挂头顶。勾选完成的行会从待办区
  挪到已完成区；已完成行右键可「恢复待办 / 删除任务」

顺延是派生状态：不落盘、不进 status，口径在 logic/task_filters.py，
时间一律走 service.now()（可注入），所以跨零点与测试都能覆盖。

两个滚动区横向滚动条永久关闭：文字过长自动省略号（elide），不撑宽行；
完整文字放在 tooltip 里，鼠标悬停可看全。
"""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QMenu,
    QSizePolicy,
)

from logic.task_filters import overdue_days, section_of

# 视觉常量集中在 ui/theme.py（暖色系），这里只引用不改含义
from ui import theme

BUBBLE_W = 230   # 固定宽度
# 固定高度：2026-09-18 从 300 提到 380 —— 常见组合「3 条顺延 + 4 条待办 + 2 条已完成」
# 正好占满；再多的行交给两个滚动区
BUBBLE_H = 380
ROW_H = 32       # 待办行固定高度
DONE_ROW_H = 24  # 已完成行固定高度（更紧凑）
OVERDUE_CAP = 3  # 顺延区最多显示几条，超出的收成一行提示

# 文字列可用宽度 = 气泡内宽 208 - 行边距 - 间隔 - 各固定列
# 待办行：208 - 8 - 12(三个间隔) - 14(标记) - 42(倒计时) - 40(状态) = 92
TEXT_MAX_W_TODO = 92
# 已完成行：208 - 8 - 4(一个间隔) - 14(标记) = 182
TEXT_MAX_W_DONE = 182
# 顺延行（2026-09-18）：208 - 8 - 8(两个间隔) - 14(标记) - 52(顺延天数) = 126
OVERDUE_ROW_H = 22
OVERDUE_DUE_W = 52
TEXT_MAX_W_OVERDUE = 126

# 状态标签配色（与面板保持一致；语义色不变，圆角/中性灰走主题）
STATUS_STYLE = {
    'done': ('完成', f'background-color: {theme.DONE_GREEN_BG}; color: {theme.DONE_GREEN}; '
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
    """头顶气泡：待办（今天+其他任务的未完成）+ 已完成（今天完成的），TaskService 信号驱动"""

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
        layout.setSpacing(3)   # 分区多了以后逐像素抠出来的间距

        # 标题行：左「📋 待办」右「⚠ N 条顺延」（没顺延时右侧留空）
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)
        title = QLabel('📋 待办')
        title.setFixedHeight(24)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title.setStyleSheet(
            f'font-weight: bold; font-size: 12px; border: none; color: {theme.ACCENT_DARK};')
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._alert = QLabel('')
        self._alert.setFixedHeight(24)
        self._alert.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._alert.setStyleSheet(
            f'color: {theme.OVERDUE}; border: none; font-size: 11px; font-weight: bold;')
        title_row.addWidget(self._alert)
        layout.addLayout(title_row)
        self._title = title

        # ---- 顺延区（有顺延才显示；最多 OVERDUE_CAP 条，其余只报数不建行）----
        self._overdue_head = QLabel('')
        self._overdue_head.setFixedHeight(18)
        self._overdue_head.setStyleSheet(
            f'color: {theme.OVERDUE}; border: none; font-size: 11px; font-weight: bold;')
        layout.addWidget(self._overdue_head)

        self._overdue_content = QWidget()
        self._overdue_content.setStyleSheet('background: transparent;')
        self._overdue_container = QVBoxLayout(self._overdue_content)
        self._overdue_container.setSpacing(2)
        self._overdue_container.setContentsMargins(0, 0, 0, 0)
        self._overdue_container.addStretch()
        layout.addWidget(self._overdue_content)

        self._overdue_more = QLabel('')
        self._overdue_more.setFixedHeight(14)
        self._overdue_more.setStyleSheet(
            f'color: {theme.TEXT_DIM}; border: none; font-size: 10px;')
        layout.addWidget(self._overdue_more)

        self._divider1 = self._make_divider()
        layout.addWidget(self._divider1)

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
        self._divider2 = self._make_divider()
        layout.addWidget(self._divider2)

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
        service.sig_day_changed.connect(self._on_day_changed)   # 跨零点重排分区

    @staticmethod
    def _make_divider():
        """1px 分隔线：顺延区 / 已完成区各自一条，没内容时整条隐藏"""
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f'background: {theme.CARD_BORDER}; border: none;')
        return line

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
        """这条任务该进哪个区：'overdue' / 'todo' / 'done' / None（不上气泡）

        口径唯一来源是 logic/task_filters.py，时间来自 service 的时钟；
        其他日期的任务不上气泡（它们由菜单面板按天管理）。
        """
        return section_of(task, self._service.now())

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
        if self._can_show(section):
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
        if section is not None and self._can_show(section):
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
        """按内存数据重建所有行（打开气泡时用）

        顺序：顺延（顺延最久的在前，只建前 OVERDUE_CAP 条）→ 今天 / 其他任务
        → 今天完成的。顺延条数由 service 全量给出，超出的部分交给提示行报数。
        """
        for refs in self._rows.values():
            refs['container'].removeWidget(refs['row'])
            refs['row'].deleteLater()
        self._rows.clear()

        now = self._service.now()
        for task in self._service.overdue()[:OVERDUE_CAP]:
            self._insert_row(task, 'overdue')
        for task in self._service.tasks():
            section = section_of(task, now)
            if section in ('todo', 'done'):
                self._insert_row(task, section)
        self._update_sections_visible()

    def _on_day_changed(self, new_today):
        """跨零点：昨天没做完的落进顺延区，三个分区与顺序都可能变，整体重排"""
        self.reload_all()

    # 兼容旧调用名
    refresh = reload_all

    def _update_sections_visible(self):
        """顺延区（含条数上限）、待办空态、已完成区显隐与计数，一处对齐"""
        self._refill_overdue()
        n_todo = self._count_section('todo')
        n_done = self._count_section('done')
        n_overdue = self._count_section('overdue')
        self._empty.setVisible(n_todo == 0)

        has_done = n_done > 0
        self._done_header.setVisible(has_done)
        self._done_scroll.setVisible(has_done)
        self._divider2.setVisible(has_done)
        if has_done:
            self._done_header.setText(f'✓ 已完成（{n_done}）')
            # 已完成区只占内容高度：否则两个滚动区按 3:2 平分，待办区明明还有地方
            # 也会挤出滚动条（已完成行 24 + 行距 2 算）
        self._done_scroll.setMaximumHeight(
            n_done * (DONE_ROW_H + 2) + 2 if has_done else 0)

        # 顺延：全量条数来自 service，行只建前 OVERDUE_CAP 条，差额交给提示行
        total = len(self._service.overdue())
        hidden = max(0, total - n_overdue)
        has_overdue = n_overdue > 0
        self._overdue_head.setVisible(has_overdue)
        self._overdue_content.setVisible(has_overdue)
        self._divider1.setVisible(has_overdue)
        self._overdue_more.setVisible(hidden > 0)
        if has_overdue:
            self._overdue_head.setText(f'⚠ 顺延 {total}')
        if hidden > 0:
            self._overdue_more.setText(f'还有 {hidden} 条，去菜单处理')
        self._alert.setText(f'⚠ {total} 条顺延' if total else '')

    def _count_section(self, section):
        return sum(1 for r in self._rows.values() if r['section'] == section)

    def _refill_overdue(self):
        """顺延区没满但还有顺延任务：把最久的那几条补齐到上限

        勾掉/删掉/搬走一条顺延后，被上限挡在外面的下一条要顶上来，
        否则它会一直躲到气泡重开为止。只重建顺延区自己的行。
        """
        want = self._service.overdue()[:OVERDUE_CAP]
        have = [tid for tid, r in self._rows.items() if r['section'] == 'overdue']
        if {t['id'] for t in want} == set(have):
            return
        for tid in have:
            refs = self._rows.pop(tid)
            refs['container'].removeWidget(refs['row'])
            refs['row'].deleteLater()
        for task in want:
            self._insert_row(task, 'overdue')

    def _can_show(self, section):
        """顺延区有条数上限：满了就不再建新行（提示行负责报数）"""
        return section != 'overdue' or self._count_section('overdue') < OVERDUE_CAP

    # ==================== 行构建 ====================

    def _container_of(self, section):
        """分区 → 承载它的布局（三个区各自独立，顺序互不干扰）"""
        if section == 'overdue':
            return self._overdue_container
        return self._task_container if section == 'todo' else self._done_container

    def _insert_row(self, task, section):
        container = self._container_of(section)
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

        due = None
        if section == 'todo':
            row.setFixedHeight(ROW_H)
            # 无条件创建，没时长时 hide —— 否则"改时长"把 0 改成 >0 时这行
            # 没有 label 可更新，只能整行重建
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
            row.setFixedHeight(DONE_ROW_H if section == 'done' else OVERDUE_ROW_H)
            row.setProperty('task_id', task['id'])
            row.installEventFilter(self)   # 右键 → 移到今天 / 恢复待办 / 删除任务
            timer = None
            status = None
            due = None
            if section == 'overdue':
                # 顺延行右侧补一列「顺延 N 天」，固定列宽保证每行右边对齐
                due = QLabel()
                due.setFixedWidth(OVERDUE_DUE_W)
                due.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                due.setStyleSheet(
                    f'color: {theme.OVERDUE}; border: none; font-size: 11px; font-weight: bold;')
                layout.addWidget(due)

        refs = {'row': row, 'marker': marker, 'text': text, 'timer': timer,
                'status': status, 'due': due, 'section': section,
                'container': self._container_of(section)}
        self._rows[task['id']] = refs
        self._apply_row(task, refs)
        return row

    def _apply_row(self, task, refs):
        """把一条任务的当前状态刷到已有控件上（不新建 widget）"""
        done = task['done']
        section = refs['section']

        # 行首标记：顺延 ⚠ / 完成 ✓ / 待办圆点（棕=今天、灰=其他任务）
        if section == 'overdue':
            refs['marker'].setText('⚠')
            refs['marker'].setStyleSheet(
                f'color: {theme.OVERDUE}; border: none; font-size: 11px; font-weight: bold;')
        elif done:
            refs['marker'].setText('✓')
            refs['marker'].setStyleSheet(
                f'color: {theme.DONE_GREEN}; border: none; font-size: 12px; font-weight: bold;')
        else:
            refs['marker'].setText('•')
            color = (theme.DOT_UNDATED if task.get('due_date') is None
                     else theme.DOT_TODAY)
            refs['marker'].setStyleSheet(
                f'color: {color}; border: none; font-size: 12px;')

        if refs['due'] is not None:
            days = overdue_days(task, self._service.now())
            refs['due'].setText(f'顺延 {days} 天' if days > 0 else '')

        label = refs['text']
        font = label.font()
        font.setUnderline(done)
        label.setFont(font)
        label.setStyleSheet(
            f'color: {theme.TEXT_DIM}; border: none; font-size: 12px;' if done
            else f'color: {theme.TEXT}; border: none; font-size: 12px;'
        )
        max_w = {'todo': TEXT_MAX_W_TODO, 'overdue': TEXT_MAX_W_OVERDUE}.get(
            section, TEXT_MAX_W_DONE)
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
                refs = self._rows.get(task_id)
                if refs is not None and refs['section'] == 'overdue':
                    self._show_overdue_menu(task_id)
                else:
                    self._show_done_menu(task_id)
                return True
        return super().eventFilter(obj, event)

    def _show_overdue_menu(self, task_id):
        """顺延行右键：先处置顺延（移到今天 / 删除），不在气泡里做别的"""
        menu = QMenu(self)
        move_action = menu.addAction('移到今天')
        delete_action = menu.addAction('删除任务')
        chosen = menu.exec_(QCursor.pos())
        if chosen == move_action:
            self._service.move_to_today(task_id)
        elif chosen == delete_action:
            self._service.remove_task(task_id)

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


def _timer_style(task, remaining_s):
    """倒计时底色：归零红底 > 状态色系"""
    if remaining_s <= 0:
        return TIMER_STYLE['zero']
    return TIMER_STYLE.get(task.get('status', 'todo'), TIMER_STYLE['todo'])
