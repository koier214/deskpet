"""待办事项面板 —— 标准窗口，TaskService 的纯视图

面板不再持有数据、不再持有计时器、不再读写 JSON：所有用户操作转发给 service，
所有显示更新由 service 的信号驱动。这样关掉面板倒计时照走（原来 closeEvent 里
停表是"关了面板就永远等不到提醒"的根因）。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QLabel, QCheckBox, QScrollArea, QFrame, QInputDialog,
)

STATUS_STYLE = {
    'done': ('完成', 'background-color: #e8f5e9; color: #2e7d32; '
                    'font-size: 12px; font-weight: bold; border-radius: 6px;'),
    'in_progress': ('进行中', 'background-color: #ffebee; color: #c62828; '
                             'font-size: 12px; font-weight: bold; border-radius: 6px;'),
    'paused': ('暂停中', 'background-color: #fff3e0; color: #e65100; '
                        'font-size: 12px; font-weight: bold; border-radius: 6px;'),
    'todo': ('待做', 'background-color: #f5f5f5; color: #616161; '
                    'font-size: 12px; border-radius: 6px;'),
}


class TaskPanel(QWidget):
    """待办列表面板（只渲染 + 转发操作）"""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self.pet_name = service.pet_name   # 兼容保留

        # {task_id: {"row","checkbox","text_label","timer_label","status_label"}}
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
        self.resize(420, 500)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- 输入行 ----
        input_row = QHBoxLayout()
        self._task_input = QLineEdit()
        self._task_input.setPlaceholderText('输入新任务，回车添加...')
        self._task_input.returnPressed.connect(self._on_add_task)
        input_row.addWidget(self._task_input)

        add_btn = QPushButton('添加')
        add_btn.clicked.connect(self._on_add_task)
        input_row.addWidget(add_btn)
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
            self._task_list_layout.removeWidget(row_data["row"])
            row_data["row"].deleteLater()
        self._task_rows.clear()

        for task in self._service.tasks():
            row_widget = self._build_task_row(task)
            # 插入到 stretch 之前
            self._task_list_layout.insertWidget(self._task_list_layout.count() - 1, row_widget)

    def _build_task_row(self, task):
        """为单个任务构建一行，返回 QWidget"""
        tid = task["id"]
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # 复选框
        cb = QCheckBox()
        cb.setChecked(task["done"])
        cb.stateChanged.connect(lambda state, t=tid: self._on_task_checked(t, state))
        layout.addWidget(cb)

        # 任务文本
        text_label = QLabel(task["text"])
        text_label.setWordWrap(True)
        layout.addWidget(text_label, 1)  # stretch=1，自动撑开

        # 计时显示
        timer_label = QLabel(self._format_seconds(task.get("timer_remaining_s", 0)))
        timer_label.setFixedWidth(55)
        timer_label.setAlignment(Qt.AlignCenter)
        timer_label.setCursor(Qt.PointingHandCursor)
        timer_label.mousePressEvent = lambda e, t=tid: self._on_task_timer_click(t)
        layout.addWidget(timer_label)

        # 状态标签
        status_label = QLabel()
        status_label.setFixedWidth(42)
        status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_label)

        # Set 按钮
        set_btn = QPushButton('设时')
        set_btn.setFixedWidth(40)
        set_btn.clicked.connect(lambda checked, t=tid: self._on_set_timer(t))
        layout.addWidget(set_btn)

        # 删除按钮
        del_btn = QPushButton('✕')
        del_btn.setFixedWidth(30)
        del_btn.clicked.connect(lambda checked, t=tid: self._on_delete_task(t))
        layout.addWidget(del_btn)

        # 存储引用
        self._task_rows[tid] = {
            "row": row,
            "checkbox": cb,
            "text_label": text_label,
            "timer_label": timer_label,
            "status_label": status_label,
        }

        # 应用样式（必须在 _task_rows 存储之后，因为 _apply_row_style 会反查）
        self._apply_row_style(text_label, timer_label, task)

        return row

    def _apply_row_style(self, text_label, timer_label, task):
        """根据任务状态设置文字样式"""
        if task["done"]:
            font = text_label.font()
            font.setStrikeOut(True)
            text_label.setFont(font)
            text_label.setStyleSheet('color: #999;')
        else:
            font = text_label.font()
            font.setStrikeOut(False)
            text_label.setFont(font)
            text_label.setStyleSheet('')

        # 计时状态着色
        remaining = task.get("timer_remaining_s", 0)
        counting = (self._service.is_running()
                    and task["id"] == self._service.active_task_id)
        if counting and remaining > 0:
            timer_label.setStyleSheet('background-color: #F4EBE1; color: #96704F; '
                                      'border-radius: 6px; font-weight: bold;')
        elif remaining == 0 and task.get("timer_total_s", 0) > 0:
            timer_label.setStyleSheet('background-color: #FFEBEE; color: #C62828; '
                                      'border-radius: 6px; font-weight: bold;')
        else:
            timer_label.setStyleSheet('')

        # 状态标签
        row_data = self._task_rows.get(task["id"])
        if row_data:
            sl = row_data.get("status_label")
            if sl:
                text, style = STATUS_STYLE.get(
                    task.get("status", "todo"), STATUS_STYLE["todo"])
                sl.setText(text)
                sl.setStyleSheet(style)

    # ==================== 用户操作：一律转发给 service ====================

    def _on_add_task(self):
        text = self._task_input.text().strip()
        if not text:
            return

        # 弹窗设置倒计时，取消则默认 25 分钟
        minutes, ok = QInputDialog.getInt(
            self, '设置倒计时', f'"{text}" 的倒计时（分钟）：',
            value=25, minValue=1, maxValue=480, step=5,
        )
        if not ok:
            minutes = 25  # 点取消 → 默认 25 分钟

        # 不自己建行：交给 sig_task_added 槽，保证面板和气泡走同一条路径
        self._service.add_task(text, minutes)

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
        current_min = task.get("timer_total_s", 0) // 60
        minutes, ok = QInputDialog.getInt(
            self, '设置倒计时', f'"{task["text"]}" 的倒计时（分钟）：',
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
        self._task_list_layout.removeWidget(row_data["row"])
        row_data["row"].deleteLater()

    def _on_svc_updated(self, task_id):
        self._refresh_row(task_id)

    def _on_svc_tick(self, task_id, remaining_s):
        """每秒热路径：只改倒计时文本，不重算样式、不碰磁盘"""
        row_data = self._task_rows.get(task_id)
        if row_data:
            row_data["timer_label"].setText(self._format_seconds(remaining_s))

    # ==================== 辅助方法 ====================

    def _refresh_row(self, task_id):
        """按内存快照原地重刷一行（不重建 widget）"""
        task = self._service.task(task_id)
        row_data = self._task_rows.get(task_id)
        if task is None or row_data is None:
            return

        row_data["timer_label"].setText(
            self._format_seconds(task.get("timer_remaining_s", 0)))

        # 必须屏蔽信号：归零自动勾选 → stateChanged → set_done → sig_task_updated
        # → 再 setChecked，不掐断就是个信号回环
        cb = row_data["checkbox"]
        cb.blockSignals(True)
        cb.setChecked(task["done"])
        cb.blockSignals(False)

        self._apply_row_style(row_data["text_label"], row_data["timer_label"], task)

    def _refresh_all_rows(self):
        """原地刷新所有行的文本与样式（不重建 widget）"""
        for task in self._service.tasks():
            self._refresh_row(task["id"])

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
