"""一二菜单面板 —— 标签页式功能中心：待办（日历）/ 固定任务 / 使用统计

待办页 2026-09-18 改版、2026-09-22 二次评审（草图 todo-enhancement-mockup）：

  - 三个快捷入口：今天 / 顺延 / 其他任务，各带条数；有顺延时「顺延」入口整体转红
  - 日历三态圆点 + 图例：未到期（棕）/ 已顺延（红）/ 已完成（灰）
    （「未完成」和「顺延」不是一回事：前者含还没到日子的今天与将来）
  - 列表标题行：标题 + 副标题 +「全部移到今天」（有顺延时才出现）
  - 任务行右侧三列固定列宽、顺延行行首红条；行逻辑在 ui/task_panel.py，本文件不写第二份
  - 输入行：回车或点右侧「添加」都能新增，旁边两个下拉选归属日期与倒计时时长
  - 行右键菜单：顺延任务多一条「移到今天」

TaskTab 继承 TaskPanel 复用行构建 / 信号接线，不写第二份行逻辑；覆盖的部分：
  - _init_ui：不建窗口壳，建「入口 + 日历 + 图例 + 标题行 + 列表 + 输入行」
  - _visible_tasks / _task_visible：按当前模式挑任务
  - _on_add_task：读归属下拉，不弹窗

FixedTaskTab 是第三页（🔁 固定任务）：规则增删 / 启用暂停、以及「今天已追加几条」
全部转发给 FixedTaskService，本文件不自己记规则、不自己算「今天该跑哪几条」；
规则命中当天时由 service 往 TaskService 追加一条普通任务（列表里带「固定」徽章）。
视图依旧是纯视图：数据操作一律转发给 TaskService；「今天」一律走
service.now() / today_str()（唯一口径在 logic/task_filters.py）；本文件里只有纯函数
_rel_word / _day_title 在没传 today 时才回落到系统今天（老调用方兼容）。
"""
from datetime import date, timedelta

from PySide6.QtCore import Qt, QDate, QPointF, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QCalendarWidget, QTabWidget, QMenu, QInputDialog, QDialog, QScrollArea,
    QFrame, QApplication, QComboBox,
)

from logic.task_filters import is_overdue, overdue_days
from logic.fixed_task_service import FREQ_LABELS, FREQ_TEXT
from ui.task_panel import TaskPanel, DUE_W, TIMER_W, STATUS_W, DEL_W
from ui.usage_window import UsageWidget
from ui.account_tab import AccountTab
from ui import theme

WIN_W, WIN_H = 500, 620   # 620：入口栏 + 图例 + 批量按钮之后给列表留出空间

# 三个快捷入口（顺序即按钮顺序）；'overdue' 是内部键，UI 上一律叫「顺延」
ENTRY_DEFS = (('today', '今天'), ('overdue', '顺延'), ('undated', '其他任务'))

# 输入行的倒计时时长档位（待办页与固定任务页共用同一套）
TIMER_CHOICES = (('⏱ 不计时', 0), ('⏱ 25 分钟', 25), ('⏱ 30 分钟', 30),
                 ('⏱ 35 分钟', 35), ('⏱ 40 分钟', 40), ('⏱ 45 分钟', 45))
DEFAULT_TIMER_INDEX = 1   # 默认 25 分钟


def _base_day(today=None):
    """基准日：给了 'YYYY-MM-DD' 就用它，否则系统今天（测试可注入）"""
    return date.fromisoformat(today) if today else date.today()


def _rel_word(date_str, today=None):
    """'2026-09-05' → 今天/明天/昨天；其他返回空串"""
    try:
        d = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return ''
    return {0: '今天', 1: '明天', -1: '昨天'}.get((d - _base_day(today)).days, '')


def _day_title(date_str, today=None):
    """'2026-09-05' → '9月5日（今天）'"""
    d = date.fromisoformat(date_str)
    title = f'{d.month}月{d.day}日'
    rel = _rel_word(date_str, today)
    return f'{title}（{rel}）' if rel else title


def _short_day(date_str):
    """'2026-09-20' → '9月20日'"""
    d = date.fromisoformat(date_str)
    return f'{d.month}月{d.day}日'


def _pick_date(parent, initial_str):
    """弹一个带日历的小对话框选日期；取消返回 None"""
    dlg = QDialog(parent)
    dlg.setWindowTitle('选择日期')
    lay = QVBoxLayout(dlg)
    cal = QCalendarWidget(dlg)
    cal.setGridVisible(True)
    cal.setFirstDayOfWeek(Qt.Monday)
    initial = QDate.fromString(initial_str, 'yyyy-MM-dd')
    cal.setSelectedDate(initial if initial.isValid() else QDate.currentDate())
    lay.addWidget(cal)
    ok = QPushButton('确定')
    ok.clicked.connect(dlg.accept)
    lay.addWidget(ok)
    if dlg.exec() == QDialog.Accepted:
        return cal.selectedDate().toString('yyyy-MM-dd')
    return None


def _legend_item(color, text):
    """图例里的一颗小圆点 + 说明文字（颜色一律从 ui/theme.py 取）"""
    item = QWidget()
    lay = QHBoxLayout(item)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    dot = QLabel()
    dot.setFixedSize(6, 6)
    dot.setStyleSheet(f'background: {color}; border-radius: 3px;')
    lay.addWidget(dot)
    label = QLabel(text)
    label.setObjectName('legendText')
    lay.addWidget(label)
    return item


class _MarkCalendar(QCalendarWidget):
    """日历：有任务的日子在数字下方画一颗三态圆点

    圆点颜色来自 logic/task_filters.py 的日期状态（open / overdue / done），
    选中日画白点（压在选中底色上）；颜色只在 ui/theme.py 定义。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {}

    def set_states(self, states):
        """{date_str: 'open'/'overdue'/'done'}；只重画格子，不动选中日"""
        self._states = states or {}
        self.updateCells()

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        state = self._states.get(date.toString('yyyy-MM-dd'))
        if not state:
            return
        color = QColor(theme.CAL_DOT.get(state, theme.CAL_DOT_OPEN))
        if date == self.selectedDate():
            color = QColor(255, 255, 255, 235)   # 选中日：白点压在棕色选中底上
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(rect.center().x(), rect.bottom() - 4), 2.5, 2.5)
        painter.restore()


class TaskTab(TaskPanel):
    """菜单面板的待办页：入口 + 日历 + 按天分组列表 + 右键菜单"""

    def __init__(self, service, parent=None):
        # 必须在 super().__init__ 之前：_init_ui 与 _build_all_task_rows 都会用到
        self._today = service.today_str()
        self._mode = 'today'              # today / overdue / undated / day
        self._selected_date = self._today
        self._marked_dates = set()        # 日历上有标记的日子（三态任一）
        super().__init__(service, parent)
        # 入口条数、标题副标题、日历标记要跟着任何数据变化走
        service.sig_task_added.connect(self._on_data_changed)
        service.sig_task_removed.connect(self._on_data_changed)
        service.sig_task_updated.connect(self._on_data_changed)
        service.sig_day_changed.connect(self._on_day_changed)
        self._refresh_view()

    # ==================== UI（覆盖：不建窗口壳） ====================

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # ---- 三个快捷入口：今天 / 顺延 / 其他任务 ----
        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        self._entry_btns = {}
        for key, _label in ENTRY_DEFS:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setObjectName('entryBtn')
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=key: self._on_entry_clicked(k))
            entry_row.addWidget(btn)
            self._entry_btns[key] = btn
        entry_row.addStretch(1)
        layout.addLayout(entry_row)

        # ---- 日历（三态圆点，无网格线）+ 图例 ----
        self._calendar = _MarkCalendar()
        self._calendar.setGridVisible(False)
        self._calendar.setFirstDayOfWeek(Qt.Monday)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self._calendar.selectionChanged.connect(self._on_date_selected)
        layout.addWidget(self._calendar)

        legend = QHBoxLayout()
        legend.setSpacing(12)
        legend.setContentsMargins(2, 0, 2, 0)
        legend.addWidget(_legend_item(theme.CAL_DOT_OPEN, '未到期'))
        legend.addWidget(_legend_item(theme.CAL_DOT_OVERDUE, '已顺延'))
        legend.addWidget(_legend_item(theme.CAL_DOT_DONE, '已完成'))
        legend.addStretch(1)
        layout.addLayout(legend)

        # ---- 当前视图：标题 + 副标题 + 批量处置 ----
        nav_row = QHBoxLayout()
        nav_row.setSpacing(8)
        self._day_header = QLabel()
        self._day_header.setObjectName('dayHeader')
        nav_row.addWidget(self._day_header)
        self._day_sub = QLabel()
        self._day_sub.setObjectName('daySub')
        nav_row.addWidget(self._day_sub)
        nav_row.addStretch(1)
        self._batch_btn = QPushButton('全部移到今天')
        self._batch_btn.setObjectName('batchBtn')
        self._batch_btn.setCursor(Qt.PointingHandCursor)
        self._batch_btn.setToolTip('把所有顺延任务改到今天（不自动搬，只有点了才搬）')
        self._batch_btn.clicked.connect(self._on_batch_move)
        nav_row.addWidget(self._batch_btn)
        layout.addLayout(nav_row)

        # ---- 任务列表（同 TaskPanel 结构，行逻辑复用） ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setObjectName('taskScroll')
        self._scroll.viewport().setObjectName('taskScrollViewport')
        self._scroll_content = QWidget()
        self._scroll_content.setObjectName('taskScrollContent')
        self._task_list_layout = QVBoxLayout(self._scroll_content)
        self._task_list_layout.setSpacing(4)
        self._task_list_layout.setContentsMargins(0, 0, 0, 4)
        self._task_list_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

        # ---- 输入行：回车或「添加」按钮都能新增；两个下拉（归属日期 / 时长） ----
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText('输入新任务')
        self._task_input.setObjectName('taskInput')
        self._task_input.returnPressed.connect(self._on_add_task)
        input_row.addWidget(self._task_input, 1)

        self._belong_combo = QComboBox()
        self._belong_combo.setObjectName('taskSelect')
        self._belong_combo.setToolTip('新任务归到哪一天')
        input_row.addWidget(self._belong_combo)

        self._timer_combo = QComboBox()
        self._timer_combo.setObjectName('taskSelect')
        self._timer_combo.setToolTip('新任务的倒计时时长')
        for label, minutes in TIMER_CHOICES:
            self._timer_combo.addItem(label, minutes)
        self._timer_combo.setCurrentIndex(DEFAULT_TIMER_INDEX)
        input_row.addWidget(self._timer_combo)

        self._add_btn = QPushButton('添加')
        self._add_btn.setObjectName('addBtn')
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setToolTip('把输入框里的内容加成新任务（回车同效）')
        self._add_btn.clicked.connect(self._on_add_task)
        input_row.addWidget(self._add_btn)

        layout.addLayout(input_row)

    # ==================== 模式与筛选 ====================

    def _on_entry_clicked(self, key):
        """点入口 = 切模式（day 模式点入口也切走，不会两个都亮）"""
        self._mode = key
        self._refresh_view(reset_belong=True)

    def _on_date_selected(self):
        """点日历 = 看那一天（顺延/今天/其他任务之外的任意日期）"""
        self._selected_date = self._calendar.selectedDate().toString('yyyy-MM-dd')
        self._mode = 'day'
        self._refresh_view(reset_belong=True)

    def _visible_tasks(self):
        """当前模式下显示哪些任务，顺序：欠账 → 未完成 → 已完成"""
        if self._mode == 'overdue':
            return list(self._service.overdue())
        if self._mode == 'undated':
            return list(self._service.undated())
        if self._mode == 'day':
            return self._open_first(self._service.tasks_on(self._selected_date))
        # today：先看欠账，再看今天（未完成在前），最后是今天做完的
        return list(self._service.overdue()) + self._open_first(
            self._service.tasks_on(self._today))

    @staticmethod
    def _open_first(tasks):
        """未完成在前、已完成在后；各自保持 service 的插入序"""
        return ([t for t in tasks if not t['done']]
                + [t for t in tasks if t['done']])

    def _task_visible(self, task):
        """信号槽里判断某条任务当前是否该出现在列表里"""
        return task['id'] in {t['id'] for t in self._visible_tasks()}

    # ==================== 刷新 ====================

    def _refresh_view(self, reset_belong=False):
        """全量重刷。reset_belong：模式/选中日刚变过，归属下拉回到该模式的默认值"""
        self._build_all_task_rows()
        self._refresh_entries()
        self._refresh_header()
        self._refresh_calendar_states()
        self._refresh_belong_combo(reset=reset_belong)

    def _refresh_entries(self):
        """三个入口的文案与条数；有顺延时「顺延」入口转红"""
        n_overdue = len(self._service.overdue())
        n_undated = len(self._service.undated())
        n_today_open = len([t for t in self._service.tasks_on(self._today)
                            if not t['done']])
        n_today = n_overdue + n_today_open
        texts = {
            'today': f'今天 {n_today}',
            'overdue': f'顺延 {n_overdue}',
            'undated': f'其他任务 {n_undated}',
        }
        # 数字是"还没做完的"，今天视图里做完的排在最后，所以行数可能比数字多
        tips = {
            'today': f'顺延 {n_overdue} 条，今天还有 {n_today_open} 条没做完（做完的排在最后）',
            'overdue': (f'{n_overdue} 条没做完，顺延最久的排最前' if n_overdue
                        else '目前没有顺延任务'),
            'undated': f'{n_undated} 条没有安排到具体某天，不会被顺延',
        }
        for key, btn in self._entry_btns.items():
            btn.setText(texts[key])
            btn.setToolTip(tips[key])
            btn.setChecked(key == self._mode)
            name = 'entryBtnAlert' if (key == 'overdue' and n_overdue) else 'entryBtn'
            if btn.objectName() != name:
                btn.setObjectName(name)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

    def _refresh_header(self):
        """标题 + 副标题 +「全部移到今天」显隐"""
        n_overdue = len(self._service.overdue())
        if self._mode == 'overdue':
            title = '顺延'
            if n_overdue:
                worst = overdue_days(self._service.overdue()[0], self._service.now())
                sub = f'{n_overdue} 条没做完，最早一条顺延了 {worst} 天'
            else:
                sub = '没有顺延任务'
        elif self._mode == 'undated':
            title = '其他任务'
            sub = '没有安排到具体某天，不会被顺延'
        elif self._mode == 'day':
            title = _day_title(self._selected_date, self._today)
            on_day = self._service.tasks_on(self._selected_date)
            n_open = len([t for t in on_day if not t['done']])
            sub = (f'{n_open} 条未完成 · {len(on_day) - n_open} 条已完成'
                   if on_day else '这天没有任务')
        else:   # today
            title = _day_title(self._today, self._today)
            n_open = len([t for t in self._service.tasks_on(self._today)
                          if not t['done']])
            sub = f'顺延 {n_overdue} · 待办 {n_open}'
        self._day_header.setText(title)
        self._day_sub.setText(sub)
        self._batch_btn.setVisible(n_overdue > 0 and self._mode != 'undated')

    def _refresh_calendar_states(self):
        """日历三态：未到期（棕）/ 已顺延（红）/ 已完成（灰）"""
        states = self._service.date_states()
        self._calendar.set_states(states)
        self._marked_dates = {QDate.fromString(d, 'yyyy-MM-dd') for d in states}
        self._marked_dates = {qd for qd in self._marked_dates if qd.isValid()}

    def _refresh_belong_combo(self, reset=False):
        """归属下拉：候选项跟着模式走

        reset=False 时保留用户当前的选择（数据刷新不该改输入行的选择），
        reset=True 时回到该模式的默认值（切模式 / 点日期 / 跨天时用）。
        """
        had_items = self._belong_combo.count() > 0
        prev = self._belong_combo.currentData() if had_items else None
        tomorrow = (date.fromisoformat(self._today)
                    + timedelta(days=1)).strftime('%Y-%m-%d')

        items = []
        # day 模式看的是"其他日期"时，把那天也做成一个候选（否则只能选今天/明天）
        if self._mode == 'day' and self._selected_date not in (self._today, tomorrow):
            items.append((f'归属：{_short_day(self._selected_date)}', self._selected_date))
        items.append(('归属：今天', self._today))
        items.append(('归属：明天', tomorrow))
        items.append(('归属：其他任务', None))

        default = (self._selected_date if self._mode == 'day'
                   else None if self._mode == 'undated' else self._today)
        values = [v for _, v in items]
        target = prev if (had_items and not reset and prev in values) else default
        if target not in values:
            target = values[0]

        self._belong_combo.blockSignals(True)
        self._belong_combo.clear()
        for label, value in items:
            self._belong_combo.addItem(label, value)
        self._belong_combo.setCurrentIndex(values.index(target))
        self._belong_combo.blockSignals(False)

    def _on_data_changed(self, *args):
        """增删改都不重建行（行自己处理），只刷新入口条数/标题/日历标记"""
        self._refresh_entries()
        self._refresh_header()
        self._refresh_calendar_states()

    def _on_day_changed(self, new_today):
        """跨零点：昨天没做完的自动变成顺延，分组、标题、日历全部重算"""
        self._today = new_today
        self._refresh_view(reset_belong=True)

    # ==================== 行增删（覆盖：按当前模式过滤） ====================

    def _build_all_task_rows(self):
        for row_data in self._task_rows.values():
            self._task_list_layout.removeWidget(row_data['row'])
            row_data['row'].deleteLater()
        self._task_rows.clear()
        for task in self._visible_tasks():
            row = self._build_task_row(task)
            self._task_list_layout.insertWidget(
                self._task_list_layout.count() - 1, row)

    def _on_svc_added(self, task_id):
        if task_id in self._task_rows:
            return
        task = self._service.task(task_id)
        if task is None or not self._task_visible(task):
            return
        row = self._build_task_row(task)
        self._task_list_layout.insertWidget(
            self._task_list_layout.count() - 1, row)

    def _on_svc_updated(self, task_id):
        """updated 可能改了 due_date / 完成状态：行可能要移入或移出当前列表"""
        task = self._service.task(task_id)
        if task is None:
            return
        has_row = task_id in self._task_rows
        visible = self._task_visible(task)
        if visible and not has_row:
            row = self._build_task_row(task)
            self._task_list_layout.insertWidget(
                self._task_list_layout.count() - 1, row)
        elif not visible and has_row:
            row_data = self._task_rows.pop(task_id)
            self._task_list_layout.removeWidget(row_data['row'])
            row_data['row'].deleteLater()
        else:
            self._refresh_row(task_id)

    def _build_task_row(self, task):
        """复用父类行构建（固定列宽 + 顺延红条），再挂右键菜单"""
        row = super()._build_task_row(task)
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, tid=task['id'], r=row: self._show_task_menu(tid, r.mapToGlobal(pos)))
        return row

    # ==================== 添加（覆盖：读归属下拉，不弹窗） ====================

    def _on_add_task(self):
        """回车 / 点「添加」：按归属下拉与时长下拉落一条任务"""
        text = self._task_input.text().strip()
        if not text:
            return
        due = self._belong_combo.currentData()
        minutes = int(self._timer_combo.currentData() or 0)
        self._service.add_task(text, minutes, due_date=due)
        self._task_input.clear()
        self._task_input.setFocus()

    def _on_batch_move(self):
        """把顺延全部搬到今天：搬完重刷一次（搬动本身不自动发生）"""
        if self._service.move_overdue_to_today():
            self._refresh_view()

    # ==================== 行右键菜单 ====================

    def _show_task_menu(self, task_id, global_pos):
        task = self._service.task(task_id)
        if task is None:
            return
        now = self._service.now()
        late = is_overdue(task, now)
        menu = QMenu(self)

        due = task.get('due_date')
        if due:
            rel = _rel_word(due, self._today)
            belong = f'属于：{due}（{rel}）' if rel else f'属于：{due}'
        else:
            belong = '属于：其他任务'
        if late:
            belong += f'　顺延 {overdue_days(task, now)} 天'
        belong_action = menu.addAction(belong)
        belong_action.setEnabled(False)
        menu.addSeparator()

        act_move_today = menu.addAction('移到今天') if late else None
        running = (self._service.is_running()
                   and self._service.active_task_id == task_id)
        act_timer = menu.addAction('暂停计时' if running else '开始计时')
        act_set = menu.addAction('修改时长…')
        act_edit = menu.addAction('编辑文字…')

        move_menu = menu.addMenu('移到其他日期')
        act_today = move_menu.addAction('今天')
        act_tomorrow = move_menu.addAction('明天')
        act_pick = move_menu.addAction('选日期…')
        act_none = move_menu.addAction('其他任务')

        menu.addSeparator()
        act_del = menu.addAction('删除')

        chosen = menu.exec_(global_pos)
        if chosen is None:
            return
        if chosen == act_move_today:
            self._service.move_to_today(task_id)
        elif chosen == act_timer:
            self._service.toggle_timer(task_id)
        elif chosen == act_set:
            self._on_set_timer(task_id)
        elif chosen == act_edit:
            self._on_edit_text(task_id)
        elif chosen == act_today:
            self._service.set_due_date(task_id, self._today)
        elif chosen == act_tomorrow:
            tomorrow = date.fromisoformat(self._today) + timedelta(days=1)
            self._service.set_due_date(task_id, tomorrow.strftime('%Y-%m-%d'))
        elif chosen == act_pick:
            picked = _pick_date(self, due or self._selected_date)
            if picked:
                self._service.set_due_date(task_id, picked)
        elif chosen == act_none:
            self._service.set_due_date(task_id, None)
        elif chosen == act_del:
            self._service.remove_task(task_id)

    def _on_edit_text(self, task_id):
        task = self._service.task(task_id)
        if task is None:
            return
        text, ok = QInputDialog.getText(
            self, '编辑任务', '任务内容：', text=task['text'])
        if ok:
            self._service.set_text(task_id, text)

    # ==================== 生命周期 ====================

    def showEvent(self, event):
        super().showEvent(event)
        # 日期可能在上次关闭后变了（跨零点 / 改系统时间）：按当前口径全量重建
        self._today = self._service.today_str()
        self._refresh_view(reset_belong=True)


def _duration_text(minutes):
    """规则行的时长列文案：0 分钟写「不计时」，其余写成 mm:00

    和待办行 TaskPanel._format_seconds 是同一种 mm:ss 写法，两页的时长列
    看起来才是一回事。
    """
    minutes = max(0, int(minutes or 0))
    return '不计时' if minutes == 0 else f'{minutes:02d}:00'


class FixedTaskTab(QWidget):
    """固定任务页：说明条 + 规则列表 + 输入行（纯视图，规则归 FixedTaskService）

    右侧四列直接用 ui/task_panel.py 的同一组列宽（DUE_W / TIMER_W /
    STATUS_W / DEL_W），所以规则行和待办行的右边落在同一条竖线上。
    本页不自己记规则、不自己判断「今天该跑哪几条」——那些都在 service 里。
    """

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._rule_widgets = []      # 当前列表里的规则行 / 空态提示

        service.sig_rules_changed.connect(self._refresh)
        service.sig_generated.connect(self._on_generated)

        self._init_ui()
        self._refresh()

    # ==================== UI ====================

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # ---- 说明条：开启了记几条、今天追加了几条、删掉不补的约定 ----
        self._note = QLabel()
        self._note.setObjectName('ruleNote')
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        # ---- 规则列表（复用待办页的滚动区 objectName，滚动条样式一致） ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setObjectName('taskScroll')
        self._scroll.viewport().setObjectName('taskScrollViewport')
        self._scroll_content = QWidget()
        self._scroll_content.setObjectName('taskScrollContent')
        self._rule_list_layout = QVBoxLayout(self._scroll_content)
        self._rule_list_layout.setSpacing(6)
        self._rule_list_layout.setContentsMargins(0, 0, 0, 4)
        self._rule_list_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

        # ---- 输入行：回车或「添加」都能新增 ----
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._rule_input = QLineEdit()
        self._rule_input.setPlaceholderText('新固定任务')
        self._rule_input.setObjectName('taskInput')
        self._rule_input.returnPressed.connect(self._on_add_rule)
        input_row.addWidget(self._rule_input, 1)

        self._freq_combo = QComboBox()
        self._freq_combo.setObjectName('taskSelect')
        self._freq_combo.setToolTip('这条规则多久往待办里追加一次')
        for freq, label in FREQ_LABELS:
            self._freq_combo.addItem(label, freq)
        input_row.addWidget(self._freq_combo)

        self._timer_combo = QComboBox()
        self._timer_combo.setObjectName('taskSelect')
        self._timer_combo.setToolTip('追加出来的任务默认倒计时时长')
        for label, minutes in TIMER_CHOICES:
            self._timer_combo.addItem(label, minutes)
        self._timer_combo.setCurrentIndex(DEFAULT_TIMER_INDEX)
        input_row.addWidget(self._timer_combo)

        self._add_btn = QPushButton('添加')
        self._add_btn.setObjectName('addBtn')
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setToolTip('把输入框里的内容加成一个固定任务（回车同效）')
        self._add_btn.clicked.connect(self._on_add_rule)
        input_row.addWidget(self._add_btn)

        layout.addLayout(input_row)

    # ==================== 刷新 ====================

    def _refresh(self):
        """规则列表整体重建（规则通常只有几条，不做增量）；说明条一起更新"""
        for widget in self._rule_widgets:
            self._rule_list_layout.removeWidget(widget)
            widget.deleteLater()
        self._rule_widgets = []

        rules = self._service.rules()
        if rules:
            for rule in rules:
                widget = self._build_rule_row(rule)
                self._rule_widgets.append(widget)
                self._rule_list_layout.insertWidget(
                    self._rule_list_layout.count() - 1, widget)
        else:
            empty = QLabel('还没有固定任务')
            empty.setObjectName('ruleEmpty')
            empty.setAlignment(Qt.AlignCenter)
            self._rule_widgets.append(empty)
            self._rule_list_layout.insertWidget(
                self._rule_list_layout.count() - 1, empty)

        today = self._service.today_str()
        self._note.setText(
            f'已开启 {self._service.enabled_count()} 条 · '
            f'今天已追加 {len(self._service.generated_on(today))} 条\n'
            '每天第一次打开菜单时追加；当天删掉不会补，没做完的会自动顺延进列表')

    def _on_generated(self, day, count):
        """自动追加跑完：说明条里的「今天已追加 N 条」要跟着动"""
        self._refresh()

    def _build_rule_row(self, rule):
        """一条规则一行；列宽与待办行同源（见类 docstring）"""
        enabled = rule['enabled']
        row = QWidget()
        row.setObjectName('ruleRow' if enabled else 'ruleRowOff')
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        mark = QLabel('↻')
        mark.setObjectName('ruleMark')
        mark.setFixedWidth(16)
        mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(mark)

        text = QLabel(rule['text'])
        text.setObjectName('ruleText')
        layout.addWidget(text, 1)

        freq = QLabel(FREQ_TEXT.get(rule['freq'], ''))
        freq.setObjectName('ruleFreq')
        freq.setFixedWidth(DUE_W)
        freq.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(freq)

        chip = QLabel(_duration_text(rule['minutes']))
        chip.setFixedWidth(TIMER_W)
        chip.setAlignment(Qt.AlignCenter)
        chip.setStyleSheet(
            f'background-color: {theme.NEUTRAL_BG}; color: {theme.NEUTRAL_TEXT}; '
            f'border-radius: 6px;')
        layout.addWidget(chip)

        rid = rule['id']
        toggle = QPushButton('启用' if enabled else '暂停')
        toggle.setObjectName('ruleBtnOn' if enabled else 'ruleBtn')
        toggle.setFixedWidth(STATUS_W)
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setToolTip('点一下暂停：不再往后追加，已经追加出来的任务不受影响'
                          if enabled
                          else '点一下恢复：从下一个该跑的日子开始重新追加')
        toggle.clicked.connect(lambda checked=False, r=rid: self._on_toggle(r))
        layout.addWidget(toggle)

        del_btn = QPushButton('✕')
        del_btn.setFixedSize(DEL_W, DEL_W)
        del_btn.setObjectName('rowDel')
        del_btn.setToolTip('删除这条规则（已经追加出来的任务留着）')
        del_btn.clicked.connect(lambda checked=False, r=rid: self._on_remove(r))
        layout.addWidget(del_btn)

        return row

    # ==================== 用户操作：一律转发给 service ====================

    def _on_add_rule(self):
        """回车 / 点「添加」：按频率与时长下拉建一条规则"""
        text = self._rule_input.text().strip()
        if not text:
            return
        self._service.add_rule(text, self._freq_combo.currentData(),
                               int(self._timer_combo.currentData() or 0))
        self._rule_input.clear()
        self._rule_input.setFocus()

    def _on_toggle(self, rule_id):
        rule = self._service.rule(rule_id)
        if rule is not None:
            self._service.set_enabled(rule_id, not rule['enabled'])

    def _on_remove(self, rule_id):
        self._service.remove_rule(rule_id)


class MenuPanel(QWidget):
    # 账号页是懒加载的，造出来的时候吱一声 —— PetWindow 靠它接线（信号 ↔ 网络）
    sig_account_tab_created = Signal(object)

    """一二菜单 —— 标签页功能中心：待办 / 固定任务 / 使用统计"""

    def __init__(self, task_service, usage_service, fixed_service=None,
                 parent=None):
        super().__init__(parent)
        self._task_service = task_service
        self._usage_service = usage_service
        self._fixed_service = fixed_service

        self.setWindowTitle('一二菜单')
        self.setWindowFlags(Qt.Window)
        self.resize(WIN_W, WIN_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._tabs = QTabWidget()
        self._tabs.setObjectName('menuTabs')
        self._tabs.tabBar().setObjectName('menuTabBar')
        self._task_tab = TaskTab(task_service)
        self._tabs.addTab(self._task_tab, '📅 待办')

        # 固定任务页：老调用方没传 fixed_service 时就不加这一页（不炸）
        self._fixed_tab = None
        if fixed_service is not None:
            self._fixed_tab = FixedTaskTab(fixed_service)
            self._tabs.addTab(self._fixed_tab, '🔁 固定任务')

        self._usage_tab = UsageWidget(usage_service)
        self._tabs.addTab(self._usage_tab, '📊 使用统计')

        # 账号页：**懒加载** —— 没切过去之前不构造（AGENTS.md 的懒加载约定）。
        # 先占个空位，第一次切到这一页时才把真的 AccountTab 造出来。
        # 业务逻辑一律在 ui/account_tab.py，这里只负责挂上去。
        self._account_tab = None
        self._account_holder = QWidget()
        self._tabs.addTab(self._account_holder, '👤 账号')
        self._tabs.currentChanged.connect(self._ensure_account_tab)

        layout.addWidget(self._tabs)

        theme.apply(self)
        self._center_on_screen()

    # ---------- 对外接口 ----------

    def show_task_tab(self):
        """归零提醒抢焦点时用：确保停在待办页"""
        self._tabs.setCurrentWidget(self._task_tab)

    def account_tab(self):
        """拿到账号页；还没造过就现在造一个（PetWindow 接线时用）"""
        self._ensure_account_tab(self._tabs.indexOf(self._account_holder))
        return self._account_tab

    # ---------- 内部 ----------

    def _ensure_account_tab(self, index):
        """第一次切到账号页时才真的构造它（懒加载）"""
        if self._account_tab is not None:
            return
        if index < 0 or self._tabs.widget(index) is not self._account_holder:
            return
        self._account_tab = AccountTab()
        holder_layout = QVBoxLayout(self._account_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(self._account_tab)
        self.sig_account_tab_created.emit(self._account_tab)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.left() + (screen.width() - self.width()) // 2
        y = screen.top() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def closeEvent(self, event):
        """关闭只是隐藏：服务由 PetWindow 持有，这里只补一次落盘
        （把节流窗口里还没写出去的 tick 增量存下来，同 TaskPanel 约定）"""
        self._task_service.flush()
        if self._fixed_service is not None:
            self._fixed_service.flush()
        event.accept()
