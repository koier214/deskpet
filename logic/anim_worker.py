"""动画线程 —— 精灵帧循环播放"""
import time
import random

from PySide6.QtCore import QObject, Signal

from core import settings


class AnimationWorker(QObject):
    """QThread Worker：循环播放待机/随机动画"""

    sig_setimg = Signal()           # 通知 GUI 刷新图片
    sig_move = Signal(int, int)     # 通知 GUI 移动窗口 (dx, dy)

    def __init__(self, pet_conf):
        super().__init__()
        self.pet_conf = pet_conf
        self.is_killed = False
        self.is_paused = False

    def run(self):
        """主循环 —— 在 QThread 中运行"""
        print(f'[Animation] 启动角色: {self.pet_conf.petname}')
        while not self.is_killed:
            self._play_random_act()

            while self.is_paused:
                time.sleep(0.2)
                if self.is_killed:
                    return

    def kill(self):
        self.is_killed = True
        self.is_paused = False

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    # ---------- 动画选择 ----------
    def _play_random_act(self):
        """按概率选择并播放一个随机动画组"""
        if not self.pet_conf.random_act or random.random() < 0.85:
            acts = [self.pet_conf.default]
        else:
            r = random.random()
            cumulative = 0
            chosen = 0
            for i, prob in enumerate(self.pet_conf.act_prob):
                cumulative += prob
                if r <= cumulative:
                    chosen = i
                    break
            acts = self.pet_conf.random_act[chosen]
        self._run_acts(acts)

    # ---------- 帧播放 ----------
    def _run_acts(self, acts):
        for act in acts:
            self._run_act(act)

    def _run_act(self, act):
        """播放单个 Act 的所有帧（act_num 次循环）"""
        for _ in range(act.act_num):
            for img in act.images:
                if self.is_paused or self.is_killed:
                    return

                settings.previous_img = settings.current_img
                settings.current_img = img
                settings.previous_anchor = settings.current_anchor
                settings.current_anchor = [
                    int(i * settings.tunable_scale) for i in act.anchor
                ]
                self.sig_setimg.emit()

                # 方向位移
                if act.direction:
                    px, py = 0, 0
                    d = act.direction
                    if d == 'right':   px = act.frame_move
                    elif d == 'left':  px = -act.frame_move
                    elif d == 'up':    py = -act.frame_move
                    elif d == 'down':  py = act.frame_move
                    if px != 0 or py != 0:
                        self.sig_move.emit(int(px), int(py))

                time.sleep(act.frame_refresh)
