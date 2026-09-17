"""任务服务层 —— 数据与倒计时的唯一持有者，生命周期独立于任何窗口

为什么要这一层：倒计时原先长在 TaskPanel 上，面板一关表就停，用户关掉面板去干活
就永远等不到提醒。现在 service 由 PetWindow 在启动时创建并持有，面板和气泡都退化
成纯视图（只渲染 + 把用户操作转发进来），关掉面板倒计时照走。

严格只 import QtCore + core.task_store，不碰 QtWidgets/QtGui —— 这样
tests/test_task_service.py 能用 QCoreApplication 无头跑完整套回归。

信号契约（两条不变量，视图实现依赖它们）：
  1. sig_tick 是 sig_task_updated 的高频特例，订阅者只允许用它改 timer_label 的文本，
     不得重算样式、不得读写盘。任何会引起样式或状态标签变化的改动，一定会额外发一次
     sig_task_updated（包括"启动 B 时把 A 从进行中改成暂停中"——A、B 各发一次，
     所以视图不需要全局重刷）。
  2. 信号发出时数据已改完、status 已重算完，订阅者可以安全回查 service.task(tid)
     取最新快照。视图永远是纯读者。
"""
import time
from datetime import date, datetime

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from core.task_store import load_data, save_data
from logic.task_timer import TaskTimer

FLUSH_INTERVAL_MS = 15000   # 纯 tick 的节流窗口；结构/状态变更一律立即写

# 每条任务必须齐备的键与默认值（手工编辑过的旧 JSON 可能缺）
_FIELD_DEFAULTS = (
    ('id', ''),
    ('text', ''),
    ('done', False),
    ('timer_total_s', 0),
    ('timer_remaining_s', 0),
    ('status', 'todo'),
    ('due_date', None),
    ('done_at', None),
)


def is_done_today(task):
    """该任务算不算「今天完成」：以 done_at 时间戳为准

    旧数据/手工编辑的数据没有 done_at（或类型不对）一律不算——
    几天前完成的任务不该一直挂在头顶的已完成区里。
    """
    ts = task.get('done_at')
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False
    return datetime.fromtimestamp(ts).date() == date.today()

# 单实例注册表：同一角色同时存在两个 service 会导致双份内存副本、
# 两个表同时给同一任务倒数、写盘互相覆盖，所以直接硬失败而不是警告
_INSTANCES = {}


def _valid_date(value):
    """合法 'YYYY-MM-DD' 字符串原样返回，其余（含 None/坏格式）归 None（未安排）"""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
    return value


class TaskService(QObject):
    """待办数据 + 倒计时引擎（进程内每个角色一个实例）"""

    sig_task_added = Signal(str)      # task_id
    sig_task_removed = Signal(str)    # task_id
    sig_task_updated = Signal(str)    # task_id：done/text/timer_*/status 任一变化
    sig_tick = Signal(str, int)       # task_id, remaining_s（每秒，高频热路径）
    sig_finished = Signal(str, str)   # task_id, task_text（归零，供 PetWindow 弹提醒）

    def __init__(self, pet_name='yier', *, tick_interval_ms=1000,
                 flush_interval_ms=FLUSH_INTERVAL_MS):
        if pet_name in _INSTANCES:
            raise RuntimeError(
                f'TaskService({pet_name}) 已存在，请复用同一实例')
        super().__init__()
        _INSTANCES[pet_name] = self

        self.pet_name = pet_name
        # 整个 dict（含 pomodoro 等非 tasks 的顶层键）原样持有，
        # 写盘时也整个写回 —— 绝不能重构成 {"tasks": ...} 否则那些键会被写丢
        self._data = load_data(pet_name)
        self._dirty = False
        self._shutdown = False

        self._timer = TaskTimer(self, interval_ms=tick_interval_ms)
        self._timer.ticked.connect(self._on_ticked)
        self._timer.finished.connect(self._on_finished)

        # 单次触发、按需重新武装：空闲期零唤醒，比常驻 repeating timer 省
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(flush_interval_ms)
        self._flush_timer.timeout.connect(self.flush)

        self._normalize()

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)   # 兜底，shutdown 幂等

    # ===================== 只读查询 =====================

    def tasks(self):
        """内存唯一数据源（活列表，视图约定只读）"""
        return self._data['tasks']

    def task(self, task_id):
        """单条快照；任务量级几十条，线性扫描不建索引"""
        for t in self._data['tasks']:
            if t['id'] == task_id:
                return t
        return None

    def raw_data(self):
        """整个数据 dict（含 pomodoro），调试与测试用"""
        return self._data

    @property
    def active_task_id(self):
        return self._timer.active_task_id

    def is_running(self):
        return self._timer.is_running()

    def tasks_on(self, date_str):
        """某日期的全部任务（保持插入序）"""
        return [t for t in self._data['tasks'] if t.get('due_date') == date_str]

    def undated(self):
        """未安排任务（due_date 为 None）"""
        return [t for t in self._data['tasks'] if not t.get('due_date')]

    def done_today(self):
        """今天完成的任务（保持插入序），头顶气泡已完成区用"""
        return [t for t in self._data['tasks']
                if t.get('done') and is_done_today(t)]

    def date_counts(self):
        """日期 → 任务条数（日历标记用）"""
        counts = {}
        for t in self._data['tasks']:
            d = t.get('due_date')
            if d:
                counts[d] = counts.get(d, 0) + 1
        return counts

    # ===================== 任务 CRUD =====================

    def add_task(self, text, minutes=25, due_date=None):
        """新增任务，返回 id；空白文本返回 None

        due_date：'YYYY-MM-DD' 归属某天；None = 未安排；非法值按未安排处理。
        """
        text = (text or '').strip()
        if not text:
            return None
        seconds = max(0, int(minutes)) * 60
        # 从 _FIELD_DEFAULTS 起底：以后加字段不用记得同步这里
        task = {key: default for key, default in _FIELD_DEFAULTS}
        task.update({
            'id': self._new_id(),
            'text': text,
            'timer_total_s': seconds,
            'timer_remaining_s': seconds,
            'due_date': _valid_date(due_date),
        })
        self._data['tasks'].append(task)
        self._mark_dirty(immediate=True)
        self.sig_task_added.emit(task['id'])
        return task['id']

    def remove_task(self, task_id):
        """删除任务；若正在计时先停表"""
        task = self.task(task_id)
        if task is None:
            return False
        if self._timer.active_task_id == task_id:
            self._timer.stop()
        self._data['tasks'] = [t for t in self._data['tasks'] if t['id'] != task_id]
        self._mark_dirty(immediate=True)
        self.sig_task_removed.emit(task_id)
        return True

    def set_done(self, task_id, done):
        """勾选/取消勾选完成"""
        task = self.task(task_id)
        if task is None:
            return False
        done = bool(done)
        if done:
            if self._timer.active_task_id == task_id and self.is_running():
                task['timer_remaining_s'] = self._timer.remaining
                self._timer.stop()
        elif self._timer.active_task_id == task_id and self.is_running():
            self.pause_timer(task_id)

        task['done'] = done
        task['done_at'] = time.time() if done else None
        # 撤销完成后把表针拨回起点，否则 remaining<=0 会让任务没法直接重跑
        if not done and task['timer_remaining_s'] <= 0 < task['timer_total_s']:
            task['timer_remaining_s'] = task['timer_total_s']

        self._recompute_status(task)
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        return True

    def set_timer(self, task_id, minutes):
        """重设时长；若该任务正在计时，必须同步重启表（否则下一秒就被旧值覆写回去）"""
        task = self.task(task_id)
        if task is None:
            return False
        seconds = max(0, int(minutes)) * 60
        task['timer_total_s'] = seconds
        task['timer_remaining_s'] = seconds
        if self._timer.active_task_id == task_id and self.is_running():
            self._timer.start(task_id, seconds)
        self._recompute_status(task)
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        return True

    def set_due_date(self, task_id, due_date):
        """把任务移到另一天（或 None = 移回未安排）"""
        task = self.task(task_id)
        if task is None:
            return False
        task['due_date'] = _valid_date(due_date)
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        return True

    def set_text(self, task_id, text):
        """编辑任务文字；空白文本拒绝"""
        task = self.task(task_id)
        text = (text or '').strip()
        if task is None or not text:
            return False
        task['text'] = text
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        return True

    # ===================== 倒计时控制 =====================

    def start_timer(self, task_id):
        """启动某任务的倒计时；remaining<=0 或任务不存在则返回 False"""
        task = self.task(task_id)
        if task is None or task['timer_remaining_s'] <= 0:
            return False
        if self.is_running():
            self.pause_timer()      # 同一时刻只有一个任务计时，会把旧任务同步+发信号
        self._timer.start(task_id, task['timer_remaining_s'])
        self._recompute_status(task)
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        return True

    def pause_timer(self, task_id=None):
        """停表并把表上的读数同步回数据；task_id 非空时只停它"""
        if not self.is_running():
            return False
        active = self._timer.active_task_id
        if task_id is not None and task_id != active:
            return False
        remaining = self._timer.remaining
        self._timer.stop()
        task = self.task(active)
        if task is not None:
            task['timer_remaining_s'] = remaining
            self._recompute_status(task)
            self.sig_task_updated.emit(active)
        self._mark_dirty(immediate=True)
        return True

    def toggle_timer(self, task_id):
        """点时间标签的语义：正在计时就暂停，否则启动"""
        if self.is_running() and self._timer.active_task_id == task_id:
            return self.pause_timer(task_id)
        return self.start_timer(task_id)

    # ===================== TaskTimer 回调 =====================

    def _on_ticked(self, task_id, remaining_s):
        task = self.task(task_id)
        if task is None:
            self._timer.stop()      # 数据没了就别空转（删除与 tick 撞在同一秒时）
            return
        task['timer_remaining_s'] = remaining_s
        self._mark_dirty()          # 节流：不写盘、不发 updated，视图只改文本
        self.sig_tick.emit(task_id, remaining_s)

    def _on_finished(self, task_id):
        task = self.task(task_id)
        if task is None:
            return
        task['done'] = True
        task['timer_remaining_s'] = 0
        task['done_at'] = time.time()
        self._recompute_status(task)
        self._mark_dirty(immediate=True)
        self.sig_task_updated.emit(task_id)
        self.sig_finished.emit(task_id, task['text'])

    # ===================== 落盘 =====================

    def _mark_dirty(self, immediate=False):
        self._dirty = True
        if immediate:
            self.flush()
        elif not self._flush_timer.isActive():
            self._flush_timer.start()

    def flush(self):
        """有脏数据才写盘；幂等，不碰任何计时器

        写失败（文件被杀软占用等）时保留脏标记直接返回，留给下一次 flush 重试。
        flush 位于退出流程上，一次写盘失败绝不能把退出打断，改动也不能丢 ——
        数据本来就在内存里，晚一点落盘而已。
        """
        if not self._dirty:
            return
        try:
            save_data(self.pet_name, self._data)
        except OSError as e:
            print(f'[task_service] {self.pet_name} 写盘失败，稍后重试: {e}')
            return
        self._dirty = False

    def shutdown(self):
        """退出：停 tick + 停节流 + 落盘 + 注销单实例；幂等"""
        if self._shutdown:
            return
        self._shutdown = True
        if self.is_running():
            self.pause_timer()      # 把读数同步回数据再落盘
        self._timer.stop()
        self._flush_timer.stop()
        self._dirty = True          # shutdown 必须落盘，即使只有 tick 增量
        self.flush()
        _INSTANCES.pop(self.pet_name, None)

    # ===================== 内部 =====================

    def _recompute_status(self, task):
        """O(1) 派生状态标签，只算被改的那一条（不再全表遍历）"""
        if task['done']:
            task['status'] = 'done'
        elif self.is_running() and self._timer.active_task_id == task['id']:
            task['status'] = 'in_progress'
        elif 0 <= task['timer_remaining_s'] < task['timer_total_s']:
            task['status'] = 'paused'
        else:
            task['status'] = 'todo'

    def _normalize(self):
        """启动时把磁盘上的数据矫正成视图可以闭眼用的形状

        容忍手工编辑过的 JSON：缺键补默认、类型矫正、重复/空 id 重新分配。
        同时全量重算一次 status —— 此时必然没有表在跑，上次异常退出遗留的
        in_progress 会自动降级成 paused/todo，不会留下骗人的状态标签。
        """
        raw = self._data.get('tasks')
        tasks = [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []

        for t in tasks:
            for key, default in _FIELD_DEFAULTS:
                if key not in t:
                    t[key] = default
            t['id'] = str(t['id'])
            t['text'] = str(t['text'])
            t['done'] = bool(t['done'])
            for key in ('timer_total_s', 'timer_remaining_s'):
                try:
                    t[key] = max(0, int(t[key]))
                except (TypeError, ValueError):
                    t[key] = 0
            t['due_date'] = _valid_date(t.get('due_date'))
            if isinstance(t['done_at'], bool) or not isinstance(t['done_at'], (int, float)):
                t['done_at'] = None

        used = set()
        need_new_id = []
        for t in tasks:
            if t['id'] and t['id'] not in used:
                used.add(t['id'])
            else:
                need_new_id.append(t)
        for t in need_new_id:
            t['id'] = self._alloc_id(used)

        self._data['tasks'] = tasks
        for t in tasks:
            self._recompute_status(t)
        self._mark_dirty()      # 只标脏，交给节流窗口或退出时落盘

    @staticmethod
    def _alloc_id(used):
        """在 used 之外分配一个今天前缀的新 id，并把它加进 used"""
        today = datetime.now().strftime('%Y%m%d')
        seq = 0
        for tid in used:
            if tid.startswith(today + '_'):
                tail = tid[len(today) + 1:]
                if tail.isdigit():
                    seq = max(seq, int(tail))
        while True:
            seq += 1
            candidate = f'{today}_{seq:03d}'
            if candidate not in used:
                used.add(candidate)
                return candidate

    def _new_id(self):
        """取今天已有编号的最大值 +1，而不是"条数 +1"——删掉中间一条后后者会撞号"""
        return self._alloc_id({t['id'] for t in self._data['tasks']})
