"""一二菜单面板 —— 标签页式功能中心：待办（日历）/ 使用统计

待办面板升级成菜单中心（用户诉求 2026-09-05）：
  页1 待办：月历选日 + 当日任务列表 +「未安排」入口 + 无弹窗快速添加
  页2 使用统计：原独立统计窗内容（UsageWidget 内嵌）

TaskTab 继承 TaskPanel 复用行构建/信号接线，不写第二份行逻辑；覆盖的部分：
  - _init_ui：不建窗口壳，建「日历 + 列表 + 输入行」
  - _on_add_task：不弹倒计时弹窗（默认 25 分钟），新任务归选中日
  - 行右键菜单：归属日期 + 计时/改时长/编辑文字/换日期/删除
视图依旧是纯视图：所有数据操作转发给 TaskService。
"""
from datetime import date, timedelta

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QCalendarWidget, QTabWidget, QMenu, QInputDialog, QDialog, QScrollArea,
    QFrame, QApplication,
)

from ui.task_panel import TaskPanel
from ui.usage_window import UsageWidget
from ui import theme

WIN_W, WIN_H = 500, 580
MARK_COLOR = '#B08968'   # 日历上有任务日期的标记色（与柱状图同色系）


def _rel_word(date_str):
    """'2026-09-05' → 今天/明天/昨天；其他返回空串"""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return ''
    return {0: '今天', 1: '明天', -1: '昨天'}.get((d - date.today()).days, '')


def _day_title(date_str):
    """'2026-09-05' → '9月5日（今天）'"""
    d = date.fromisoformat(date_str)
    title = f'{d.month}月{d.day}日'
    rel = _rel_word(date_str)
    return f'{title}（{rel}）' if rel else title


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


class TaskTab(TaskPanel):
    """菜单面板的待办页：日历选日 + 当日任务列表 + 右键菜单"""

    def __init__(self, service, parent=None):
        # 必须在 super().__init__ 之前：_init_ui 会用到
        self._selected_date = date.today().strftime('%Y-%m-%d')
        self._undated_mode = False
        self._marked_dates = set()
        super().__init__(service, parent)
        # 日历标记与「未安排」计数要跟着任何数据变化走
        service.sig_task_added.connect(self._on_data_changed)
        service.sig_task_removed.connect(self._on_data_changed)
        service.sig_task_updated.connect(self._on_data_changed)
        self._refresh_header()
        self._refresh_calendar_marks()

    # ==================== UI（覆盖：不建窗口壳） ====================

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # ---- 日历 ----
        self._calendar = QCalendarWidget()
        self._calendar.setGridVisible(False)   # 卡片式日历不要网格线，靠选中底色区分
        self._calendar.setFirstDayOfWeek(Qt.Monday)
        self._calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self._calendar.selectionChanged.connect(self._on_date_selected)
        layout.addWidget(self._calendar)

        # ---- 未安排入口 + 当前列表标题 ----
        nav_row = QHBoxLayout()
        self._undated_btn = QPushButton('未安排')
        self._undated_btn.setCheckable(True)
        self._undated_btn.setFixedWidth(90)
        self._undated_btn.setObjectName('undatedBtn')
        self._undated_btn.clicked.connect(self._on_undated_clicked)
        nav_row.addWidget(self._undated_btn)
        nav_row.addStretch(1)
        self._day_header = QLabel()
        self._day_header.setObjectName('dayHeader')   # 样式见 ui/theme.py
        nav_row.addWidget(self._day_header)
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

        # ---- 输入行（默认 25 分钟，不弹窗；归属当前选中日） ----
        input_row = QHBoxLayout()
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText('输入新任务，回车添加（默认 25 分钟）')
        self._task_input.setObjectName('taskInput')
        self._task_input.returnPressed.connect(self._on_add_task)
        input_row.addWidget(self._task_input)
        add_btn = QPushButton('添加')
        add_btn.setObjectName('addBtn')
        add_btn.clicked.connect(self._on_add_task)
        input_row.addWidget(add_btn)
        layout.addLayout(input_row)

    # ==================== 选中日 / 筛选 ====================

    def _task_visible(self, task):
        due = task.get('due_date')
        if self._undated_mode:
            return not due
        return due == self._selected_date

    def _visible_tasks(self):
        if self._undated_mode:
            return self._service.undated()
        return self._service.tasks_on(self._selected_date)

    def _on_date_selected(self):
        self._selected_date = self._calendar.selectedDate().toString('yyyy-MM-dd')
        self._undated_mode = False
        self._undated_btn.setChecked(False)
        self._refresh_view()

    def _on_undated_clicked(self, checked):
        self._undated_mode = bool(checked)
        self._refresh_view()

    def _refresh_view(self):
        self._build_all_task_rows()
        self._refresh_header()
        self._refresh_calendar_marks()

    def _refresh_header(self):
        if self._undated_mode:
            self._day_header.setText(f'未安排（{len(self._service.undated())}）')
        else:
            self._day_header.setText(_day_title(self._selected_date))
        self._undated_btn.setText(f'未安排（{len(self._service.undated())}）')

    def _refresh_calendar_marks(self):
        """有任务的日子加粗着色；先清旧标记再打新标记"""
        plain = QTextCharFormat()
        for qd in self._marked_dates:
            self._calendar.setDateTextFormat(qd, plain)
        self._marked_dates = set()

        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold)
        fmt.setForeground(QColor(MARK_COLOR))
        for d in self._service.date_counts():
            qd = QDate.fromString(d, 'yyyy-MM-dd')
            if qd.isValid():
                self._calendar.setDateTextFormat(qd, fmt)
                self._marked_dates.add(qd)

    def _on_data_changed(self, *args):
        self._refresh_calendar_marks()
        self._refresh_header()

    # ==================== 行增删（覆盖：按选中日过滤） ====================

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
        """updated 可能改了 due_date：行可能要移入/移出当前列表"""
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
        """复用父类行构建，再挂右键菜单"""
        row = super()._build_task_row(task)
        row.setObjectName('taskRow')
        row.setContextMenuPolicy(Qt.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, tid=task['id'], r=row: self._show_task_menu(tid, r.mapToGlobal(pos)))
        return row

    # ==================== 添加（覆盖：不弹窗） ====================

    def _on_add_task(self):
        text = self._task_input.text().strip()
        if not text:
            return
        due = None if self._undated_mode else self._selected_date
        self._service.add_task(text, 25, due_date=due)
        self._task_input.clear()
        self._task_input.setFocus()

    # ==================== 行右键菜单 ====================

    def _show_task_menu(self, task_id, global_pos):
        task = self._service.task(task_id)
        if task is None:
            return
        menu = QMenu(self)

        due = task.get('due_date')
        if due:
            rel = _rel_word(due)
            belong = f'属于：{due}（{rel}）' if rel else f'属于：{due}'
        else:
            belong = '属于：未安排'
        belong_action = menu.addAction(belong)
        belong_action.setEnabled(False)
        menu.addSeparator()

        running = (self._service.is_running()
                   and self._service.active_task_id == task_id)
        act_timer = menu.addAction('暂停计时' if running else '开始计时')
        act_set = menu.addAction('修改时长…')
        act_edit = menu.addAction('编辑文字…')

        move_menu = menu.addMenu('移到其他日期')
        act_today = move_menu.addAction('今天')
        act_tomorrow = move_menu.addAction('明天')
        act_pick = move_menu.addAction('选日期…')
        act_none = move_menu.addAction('未安排')

        menu.addSeparator()
        act_del = menu.addAction('删除')

        chosen = menu.exec_(global_pos)
        if chosen is None:
            return
        if chosen == act_timer:
            self._service.toggle_timer(task_id)
        elif chosen == act_set:
            self._on_set_timer(task_id)
        elif chosen == act_edit:
            self._on_edit_text(task_id)
        elif chosen == act_today:
            self._service.set_due_date(task_id, date.today().strftime('%Y-%m-%d'))
        elif chosen == act_tomorrow:
            tomorrow = date.today() + timedelta(days=1)
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
        # 日期可能在上次关闭后变了（跨零点等）：按当前选中日全量重建
        self._refresh_view()


class MenuPanel(QWidget):
    """一二菜单 —— 标签页功能中心：待办 / 使用统计"""

    def __init__(self, task_service, usage_service, parent=None):
        super().__init__(parent)
        self._task_service = task_service

        self.setWindowTitle('一二菜单')
        self.setWindowFlags(Qt.Window)
        self.resize(WIN_W, WIN_H)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._tabs = QTabWidget()
        self._tabs.setObjectName('menuTabs')
        self._tabs.tabBar().setObjectName('menuTabBar')
        self._task_tab = TaskTab(task_service)
        self._usage_tab = UsageWidget(usage_service)
        self._tabs.addTab(self._task_tab, '📅 待办')
        self._tabs.addTab(self._usage_tab, '📊 使用统计')
        layout.addWidget(self._tabs)

        theme.apply(self)
        self._center_on_screen()

    # ---------- 对外接口 ----------

    def show_task_tab(self):
        """归零提醒抢焦点时用：确保停在待办页"""
        self._tabs.setCurrentWidget(self._task_tab)

    # ---------- 内部 ----------

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.left() + (screen.width() - self.width()) // 2
        y = screen.top() + (screen.height() - self.height()) // 2
        self.move(x, y)

    def closeEvent(self, event):
        """关闭只是隐藏：服务由 PetWindow 持有，这里只补一次落盘
        （把节流窗口里还没写出去的 tick 增量存下来，同 TaskPanel 约定）"""
        self._task_service.flush()
        event.accept()
