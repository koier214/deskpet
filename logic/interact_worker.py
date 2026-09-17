"""交互线程 —— 点击 (patpat) & 拖拽 (mousedrag) 处理"""
from PySide6.QtCore import QObject, Signal, QTimer, Qt

from core import settings


class InteractionWorker(QObject):
    """QThread Worker：处理点击 (patpat) 和拖拽 (mousedrag) 交互"""

    sig_setimg = Signal()          # 通知 GUI 刷新图片
    sig_act_finished = Signal()    # 交互动画结束 → GUI 恢复待机动画

    def __init__(self, pet_conf):
        super().__init__()
        self.pet_conf = pet_conf
        self.is_killed = False
        self.interact = None       # None | 'patpat' | 'mousedrag'
        self._playid = 0           # 当前动画的内部帧计数
        self._expanded_frames = [] # 展开后的帧序列（含重复）

        # 定时器驱动 tick
        self._timer = QTimer()
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(self.pet_conf.interact_speed))

    def kill(self):
        self.is_killed = True
        self._timer.stop()

    # ---------- 交互控制 ----------
    def start_interact(self, interact_type):
        self.interact = interact_type
        self._playid = 0

        if interact_type == 'patpat':
            self._build_expanded_frames(self.pet_conf.patpat)

    def stop_interact(self):
        self.interact = None
        self._playid = 0
        self._expanded_frames = []
        self.sig_act_finished.emit()

    # ---------- 帧展开（patpat 用） ----------
    def _build_expanded_frames(self, act):
        """按 frame_refresh 把 Act 的帧展开为等间隔序列"""
        ticks_per_frame = max(1, round(
            act.frame_refresh * 1000 / self.pet_conf.interact_speed
        ))
        self._expanded_frames = []
        for _ in range(act.act_num):
            for img in act.images:
                self._expanded_frames.extend([img] * ticks_per_frame)

    # ---------- 每 tick 分发 ----------
    def _tick(self):
        if self.interact is None:
            return
        elif self.interact == 'patpat':
            self._do_patpat()
        elif self.interact == 'mousedrag':
            self._do_mousedrag()

    def _do_patpat(self):
        """逐帧播放 patpat 动画，播完自动停止"""
        if self._playid < len(self._expanded_frames):
            img = self._expanded_frames[self._playid]
            settings.previous_img = settings.current_img
            settings.current_img = img
            settings.previous_anchor = settings.current_anchor
            act = self.pet_conf.patpat
            settings.current_anchor = [
                int(i * settings.tunable_scale) for i in act.anchor
            ]
            self.sig_setimg.emit()
            self._playid += 1
        else:
            self.stop_interact()

    def _do_mousedrag(self):
        """拖拽时只显示拖拽图片（窗口位移由 mouseMoveEvent 直接处理）"""
        img = self.pet_conf.drag.images[0]
        settings.previous_img = settings.current_img
        settings.current_img = img
        act = self.pet_conf.drag
        settings.previous_anchor = settings.current_anchor
        settings.current_anchor = [
            int(i * settings.tunable_scale) for i in act.anchor
        ]
        self.sig_setimg.emit()
