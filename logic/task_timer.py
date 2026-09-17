"""倒计时引擎 —— 纯逻辑，零 UI 依赖"""
from PySide6.QtCore import QObject, Signal, QTimer


class TaskTimer(QObject):
    """任务倒计时引擎：管理单个任务的倒计时，通过信号通知外部"""

    ticked = Signal(str, int)    # task_id, remaining_s（每秒发射）
    finished = Signal(str)       # task_id（倒计时归零）

    def __init__(self, parent=None, interval_ms=1000):
        super().__init__(parent)
        self._active_task_id = None
        self._remaining = 0
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._on_tick)

    def start(self, task_id, remaining_s):
        """启动倒计时"""
        self._active_task_id = task_id
        self._remaining = remaining_s
        self._timer.start()

    def stop(self):
        """停止倒计时"""
        self._active_task_id = None
        self._timer.stop()

    def is_running(self):
        return self._timer.isActive()

    @property
    def active_task_id(self):
        return self._active_task_id

    @property
    def remaining(self):
        """当前剩余秒数（暂停/改时长时用于把表上的读数同步回数据）"""
        return max(0, self._remaining)

    def _on_tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            # 先摘掉 active_task_id 再发信号：归零后若留着它，
            # 用户取消勾选时状态会被误判成"进行中"（其实没有表在跑）
            task_id = self._active_task_id
            self._remaining = 0
            self._active_task_id = None
            self._timer.stop()
            self.finished.emit(task_id)
        else:
            self.ticked.emit(self._active_task_id, self._remaining)
