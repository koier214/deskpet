"""待办事项面板 —— TaskService 的纯视图：只渲染 + 转发操作

面板不持有数据、不持有计时器、不读写 JSON：所有用户操作转发给 service，
所有显示更新由 service 的信号驱动。这样关掉面板倒计时照走（原来 closeEvent 里
停表是"关了面板就永远等不到提醒"的根因）。

行结构（2026-09-18 对齐改版，菜单面板的任务行共用这份代码）：

    复选框 | 任务文字（自适应） | 顺延 62 | 倒计时 48 | 状态 46 | ✕ 20

右侧三列固定列宽，每行的倒计时 / 状态 / 删除按钮逐列对齐；
顺延行行首加一条 3px 红竖条，非顺延行用等宽透明竖条占位——两种行的左边一致。
固定任务（每天自动追加的那类）在文字后面挂一枚「固定」小徽章（2026-09-22）。
「设时」按钮已删（改时长走行右键菜单「修改时长…」）；回车和输入行右侧的
「添加」按钮都能新增（2026-09-22 评审把按钮加回来了）。
顺延是派生状态（口径在 logic/task_filters.py），不落盘、不进 status；
UI 上不再出现「逾期」两个字（2026-09-22 评审）。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QCheckBox, QScrollArea, QFrame, QInputDialog,
)

from logic.task_filters import is_overdue, overdue_days
from ui import theme

# 右侧固定列宽：菜单面板与头顶气泡按同一套数字排版
DUE_W = 62      # 「顺延 N 天」右对齐；没顺延时留空占位
TIMER_W = 48    # 倒计时
STATUS_W = 46   # 状态 pill
DEL_W = 20      # 删除按钮

_PILL = 'font-size: 11px; border-radius: 6px; padding: 2px 0;'

# 状态 pill 文案与配色（颜色一律来自 ui/theme.py）
STATUS_STYLE = {
    'done': ('完成', f'background-color: {theme.DONE_GREEN_BG}; color: {theme.DONE_GREEN}; '
                    f'{_PILL} font-weight: bold;'),
    'in_progress': ('进行中', f'background-color: {theme.RUN_RED_BG}; color: {theme.RUN_RED}; '
                             f'{_PILL} font-weight: bold;'),
    'paused': ('暂停中', f'background-color: {theme.PAUSE_ORANGE_BG}; color: {theme.PAUSE_ORANGE}; '
                        f'{_PILL} font-weight: bold;'),
    'todo': ('待做', f'background-color: {theme.NEUTRAL_BG}; color: {theme.NEUTRAL_TEXT}; {_PILL}'),
}


class TaskPanel(QWidget):
    """待办列表面板（只渲染 + 转发操作）"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self.pet_name = service.pet_name   # 兼容保留

        # {task_id: {"row","checkbox","text_label","due_label","timer_label","status_label"}}
        self._task_rows = {}

        # 视图自己接线，不再经 PetWindow 中转（JSON 曾被当成进程内消息总线用）
        service.sig_task_added.connect(self._on_svc_added)
        service.sig_task_removed.connect(self._on_svc_removed)
        service.sig_task_updated.connect(self._on_svc_updated)
        service.sig_tick.connect(self._on_svc_tick)

        self._init_ui()
        self._build_all_task_rows()

    # ==================== UI 构建 ====================

    def _init_ui(self):
        self.setWindowTitle('一二的待办')
        self.setWindowFlags(Qt.Window)
        self.resize(440, 500)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- 输入行（回车即添加；右侧「添加」按钮走同一条路）----
        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText('输入新任务')
        self._task_input.setObjectName('taskInput')
        self._task_input.returnPressed.connect(self._on_add_task)
        input_row.addWidget(self._task_input, 1)
        self._add_btn = QPushButton('添加')
        self._add_btn.setObjectName('addBtn')
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.setToolTip('把输入框里的内容加成新任务（回车同效）')
        self._add_btn.clicked.connect(self._on_add_task)
        input_row.addWidget(self._add_btn)
        main_layout.addLayout(input_row)

        # ---- 任务滚动区 ----
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        self._scroll_content = QWidget()
        self._task_list_layout = QVBoxLayout(self._scroll_content)
        self._task_list_layout.setSpacing(4)
        self._task_list_layout.setContentsMargins(0, 0, 0, 0)
        self._task_list_layout.addStretch()  # 底部弹簧，把行推到顶部
        self._scroll.setWidget(self._scroll_content)

        main_layout.addWidget(self._scroll, 1)  # stretch=1，占满剩余空间

        # 居中显示
        self._center_on_screen()

    def _center_on_screen(self):
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.left() + (screen.width() - self.width()) // 2
        y = screen.top() + (screen.height() - self.height()) // 2
        self.move(x, y)

    # ==================== 任务行构建 ====================

    def _build_all_task_rows(self):
        """清空并重建所有任务行"""
        # 移除旧行（保留 stretch）
        for row_data in self._task_rows.values():
            self._task_list_layout.removeWidget(row_data['row'])
            row_data['row'].deleteLater()
        self._task_rows.clear()

        for task in self._service.tasks():
            row_widget = self._build_task_row(task)
            # 插入到 stretch 之前
            self._task_list_layout.insertWidget(
                self._task_list_layout.count() - 1, row_widget)

    def _build_task_row(self, task):
        """为单个任务构建一行，返回 QWidget（列宽固定，见文件头）"""
        tid = task['id']
        row = QWidget()
        row.setObjectName(self._row_object_name(task))
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(6)

        # 复选框
        cb = QCheckBox()
        cb.setChecked(task['done'])
        cb.stateChanged.connect(lambda state, t=tid: self._on_task_checked(t, state))
        layout.addWidget(cb)

        # 任务文本（自适应列，撑满剩余宽度）
        text_label = QLabel(task['text'])
        text_label.setWordWrap(True)
        layout.addWidget(text_label, 1)

        # 「固定」徽章：这一条是固定任务每天自动追加出来的（普通任务不显示）
        tag_label = QLabel('固定')
        tag_label.setObjectName('rowTag')
        tag_label.setVisible(bool(task.get('fixed')))
        layout.addWidget(tag_label)

        # 顺延天数：右对齐红字，没顺延就留空占位
        due_label = QLabel()
        due_label.setObjectName('rowDue')
        due_label.setFixedWidth(DUE_W)
        due_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(due_label)

        # 倒计时（点一下启停）
        timer_label = QLabel(self._format_seconds(task.get('timer_remaining_s', 0)))
        timer_label.setFixedWidth(TIMER_W)
        timer_label.setAlignment(Qt.AlignCenter)
        timer_label.setCursor(Qt.PointingHandCursor)
        timer_label.setToolTip('点一下开始 / 暂停计时')
        timer_label.mousePressEvent = lambda e, t=tid: self._on_task_timer_click(t)
        layout.addWidget(timer_label)

        # 状态标签
        status_label = QLabel()
        status_label.setFixedWidth(STATUS_W)
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)

        # 删除按钮
        del_btn = QPushButton('✕')
        del_btn.setFixedSize(DEL_W, DEL_W)
        del_btn.setObjectName('rowDel')
        del_btn.setToolTip('删除任务')
        del_btn.clicked.connect(lambda checked, t=tid: self._on_delete_task(t))
        layout.addWidget(del_btn)

        # 存储引用（_apply_row_style 直接用引用，不再反查 id）
        self._task_rows[tid] = {
            'row': row,
            'checkbox': cb,
            'text_label': text_label,
            'due_label': due_label,
            'timer_label': timer_label,
            'status_label': status_label,
            'tag_label': tag_label,
        }
        self._apply_row_style(self._task_rows[tid], task)

        return row

    def _row_object_name(self, task):
        """顺延行行首带红条 —— 靠 objectName 让主题 QSS 选到（见 ui/theme.py）"""
        return 'taskRowOverdue' if self._is_overdue(task) else 'taskRow'

    def _is_overdue(self, task):
        """顺延口径唯一来源：logic/task_filters.py（内部键仍叫 overdue），
        「现在」来自 service 的时钟"""
        return is_overdue(task, self._service.now())

    def _apply_row_style(self, refs, task):
        """把一条任务的文字 / 顺延 / 计时 / 状态刷到已有控件上（不新建 widget）"""
        text_label = refs['text_label']
        timer_label = refs['timer_label']

        # 完成：划线 + 灰字
        done = task['done']
        font = text_label.font()
        font.setStrikeOut(done)
        text_label.setFont(font)
        text_label.setStyleSheet(f'color: {theme.TEXT_DIM};' if done else '')

        # 顺延：红字天数 + 行首红条（同一条判定，不会一处有一处没有）
        days = overdue_days(task, self._service.now())
        refs['due_label'].setText(f'顺延 {days} 天' if days > 0 else '')
        self._apply_row_object_name(refs['row'], task)

        # 计时 chip：进行中棕底 / 归零红底 / 其余中性灰
        remaining = task.get('timer_remaining_s', 0)
        counting = (self._service.is_running()
                    and task['id'] == self._service.active_task_id)
        if counting and remaining > 0:
            timer_label.setStyleSheet(
                f'background-color: {theme.ACCENT_SOFT}; color: {theme.ACCENT_DARK}; '
                f'border-radius: 6px; font-weight: bold;')
        elif remaining <= 0 and task.get('timer_total_s', 0) > 0:
            timer_label.setStyleSheet(
                f'background-color: {theme.RUN_RED_BG}; color: {theme.RUN_RED}; '
                f'border-radius: 6px; font-weight: bold;')
        else:
            timer_label.setStyleSheet(
                f'background-color: {theme.NEUTRAL_BG}; color: {theme.NEUTRAL_TEXT}; '
                f'border-radius: 6px;')

        # 固定任务徽章：规则生成的实例才显示，不动任务行其它列
        tag_label = refs.get('tag_label')
        if tag_label is not None:
            tag_label.setVisible(bool(task.get('fixed')))

        # 状态标签
        status_label = refs.get('status_label')
        if status_label is not None:
            text, style = STATUS_STYLE.get(
                task.get('status', 'todo'), STATUS_STYLE['todo'])
            status_label.setText(text)
            status_label.setStyleSheet(style)

    def _apply_row_object_name(self, row, task):
        """顺延状态变了要换 objectName；换完必须重新 polish，QSS 才会生效"""
        name = self._row_object_name(task)
        if row.objectName() == name:
            return
        row.setObjectName(name)
        style = row.style()
        style.unpolish(row)
        style.polish(row)

    # ==================== 用户操作：一律转发给 service ====================

    def _on_add_task(self):
        """回车 / 点「添加」：默认 25 分钟倒计时，不弹窗"""
        text = self._task_input.text().strip()
        if not text:
            return
        # 不自己建行：交给 sig_task_added 槽，保证面板和气泡走同一条路径
        self._service.add_task(text, 25)
        self._task_input.clear()
        self._task_input.setFocus()

    def _on_task_checked(self, task_id, state):
        self._service.set_done(task_id, state == Qt.Checked.value)

    def _on_delete_task(self, task_id):
        self._service.remove_task(task_id)

    def _on_set_timer(self, task_id):
        task = self._service.task(task_id)
        if task is None:
            return
        current_min = task.get('timer_total_s', 0) // 60
        minutes, ok = QInputDialog.getInt(
            self, '修改时长', f'"{task["text"]}" 的倒计时（分钟）：',
            value=current_min if current_min > 0 else 25,
            minValue=1, maxValue=480, step=5,
        )
        if ok:
            self._service.set_timer(task_id, minutes)

    def _on_task_timer_click(self, task_id):
        """点击时间标签：切换计时启停"""
        self._service.toggle_timer(task_id)

    # ==================== TaskService 信号响应 ====================

    def _on_svc_added(self, task_id):
        if task_id in self._task_rows:
            return
        task = self._service.task(task_id)
        if task is None:
            return
        row_widget = self._build_task_row(task)
        self._task_list_layout.insertWidget(
            self._task_list_layout.count() - 1, row_widget)

    def _on_svc_removed(self, task_id):
        row_data = self._task_rows.pop(task_id, None)
        if row_data is None:
            return
        self._task_list_layout.removeWidget(row_data['row'])
        row_data['row'].deleteLater()

    def _on_svc_updated(self, task_id):
        self._refresh_row(task_id)

    def _on_svc_tick(self, task_id, remaining_s):
        """每秒热路径：只改倒计时文本，不重算样式、不碰磁盘"""
        row_data = self._task_rows.get(task_id)
        if row_data:
            row_data['timer_label'].setText(self._format_seconds(remaining_s))

    # ==================== 辅助方法 ====================

    def _refresh_row(self, task_id):
        """按内存快照原地重刷一行（不重建 widget）"""
        task = self._service.task(task_id)
        row_data = self._task_rows.get(task_id)
        if task is None or row_data is None:
            return

        row_data['timer_label'].setText(
            self._format_seconds(task.get('timer_remaining_s', 0)))

        # 必须屏蔽信号：归零自动勾选 → stateChanged → set_done → sig_task_updated
        # → 再 setChecked，不掐断就是个信号回环
        cb = row_data['checkbox']
        cb.blockSignals(True)
        cb.setChecked(task['done'])
        cb.blockSignals(False)

        self._apply_row_style(row_data, task)

    def _refresh_all_rows(self):
        """原地刷新所有行的文本与样式（不重建 widget）"""
        for task in self._service.tasks():
            self._refresh_row(task['id'])

    def _format_seconds(self, total_s):
        if total_s is None:
            total_s = 0
        m, s = divmod(max(0, int(total_s)), 60)
        return f'{m:02d}:{s:02d}'

    # ==================== 窗口事件 ====================

    def showEvent(self, event):
        """窗口显示时按内存数据重刷一遍"""
        super().showEvent(event)
        self._refresh_all_rows()

    def closeEvent(self, event):
        """关闭只是隐藏：绝不能停表，否则倒计时又变成"面板开着才走"

        只补一次落盘，把节流窗口里还没写出去的 tick 增量存下来。
        """
        self._service.flush()
        event.accept()
