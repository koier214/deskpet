"""使用时长服务层 —— 陪伴时长数据的唯一持有者，生命周期独立于任何窗口

照抄 TaskService 的既有模式：service 由 PetWindow 在启动时创建并持有，
统计窗退化成纯视图（只渲染 + 打开时拉数据），关窗不影响计时。

严格只 import QtCore + core.usage_store，不碰 QtWidgets/QtGui —— 这样
tests/test_usage_service.py 能用 QCoreApplication 无头跑完整套回归。

计时规则（详见 spec §二）：
  - 每 60 秒 tick 一次，时长记 float 秒（跨零点拆分零误差）
  - 睡眠/挂起保护：两次 tick 墙钟间隔 > 120s 只计 60s，不把合盖 8 小时算成陪伴
  - 跨零点：一次 tick 的间隔按零点拆给两天，会话也拆成两条
  - 每 tick 落盘一次（文件 <10KB），强杀最多丢最近 60 秒
"""
import time
from datetime import datetime, timedelta

from PySide6.QtCore import QCoreApplication, QObject, QTimer

from core.usage_store import load_data, save_data

TICK_S = 60          # 每次 tick 的标准秒数
TICK_MS = 60_000     # 默认 tick 间隔（测试可注入别的）
GAP_CAP_S = 120      # 两次 tick 墙钟间隔超过它 = 睡过/卡过，只计 TICK_S
SESSIONS_CAP = 200   # 会话记录只保留最近 200 条

# 单实例注册表：同一角色同时存在两个 service 会双份计时、写盘互相覆盖，
# 所以直接硬失败而不是警告（同 TaskService）
_INSTANCES = {}


# ===================== 纯函数（不碰 QTimer/文件/IO，直接单测） =====================

def date_key(ts):
    """Unix 时间戳 → 本地日期键 'YYYY-MM-DD'"""
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


def _next_midnight(ts):
    """ts 之后最近一个零点的时间戳"""
    dt = datetime.fromtimestamp(ts)
    nxt = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp()


def _credit_interval(data, start_ts, end_ts, sessions_cap=SESSIONS_CAP):
    """把 [start_ts, end_ts] 的时长记入对应日期桶与会话记录；跨零点自动拆分

    会话约定：运行中的会话 end_ts 恒为 None；只有跨日拆分与收尾（退出/启动时
    收上次未闭合的）才写 end_ts——强杀后靠「end_ts 缺失」识别未收尾会话。
    """
    seg_start = float(start_ts)
    end_ts = float(end_ts)
    while seg_start < end_ts:
        seg_end = min(end_ts, _next_midnight(seg_start))
        secs = seg_end - seg_start
        day = date_key(seg_start)

        bucket = data['daily'].setdefault(day, {'runtime_s': 0.0})
        bucket['runtime_s'] += secs

        sess = data['sessions'][-1] if data['sessions'] else None
        if sess is not None and sess['date'] != day and sess.get('end_ts') is None:
            sess['end_ts'] = seg_start   # 旧会话在零点/段起点结束
        sess = data['sessions'][-1] if data['sessions'] else None
        if sess is None or sess['date'] != day or sess.get('end_ts') is not None:
            sess = {'date': day, 'start_ts': seg_start, 'end_ts': None, 'runtime_s': 0.0}
            data['sessions'].append(sess)
            if len(data['sessions']) > sessions_cap:
                del data['sessions'][:len(data['sessions']) - sessions_cap]
        sess['runtime_s'] += secs
        seg_start = seg_end


def advance(data, last_ts, now, tick_s=TICK_S, gap_cap_s=GAP_CAP_S,
            sessions_cap=SESSIONS_CAP):
    """一次 tick 的纯计算；返回新的 last_ts（= now）

    - last_ts 为 None（启动后首次）：计 tick_s
    - 间隔 > gap_cap_s：睡过/卡过，只计 tick_s（而不是整个间隔）
    - 时钟回拨（间隔为负）：计 0，不崩
    - 其余：计实际间隔，吃掉定时器抖动
    """
    now = float(now)
    if last_ts is None:
        start = now - tick_s
    else:
        gap = now - float(last_ts)
        if gap <= 0:
            return now
        start = now - tick_s if gap > gap_cap_s else last_ts
    _credit_interval(data, start, now, sessions_cap)
    return now


def finalize_open_session(data, now):
    """启动收尾：上次进程被杀留下的未闭合会话（end_ts 缺失）就地收掉

    不做修补猜测：end_ts 按已存累计值推算（start + runtime），数据本身不动。
    """
    sess = data['sessions'][-1] if data['sessions'] else None
    if sess is not None and sess.get('end_ts') is None:
        sess['end_ts'] = float(sess.get('start_ts', now)) + float(sess.get('runtime_s', 0.0))


def fmt_duration(total_s):
    """秒数 → 「3 小时 05 分」/「45 秒」/「2 天 3 小时」；负数按 0 处理"""
    total_s = int(max(0, float(total_s)))
    if total_s < 60:
        return f'{total_s} 秒'
    days, rem = divmod(total_s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f'{days} 天')
    if hours or days:
        parts.append(f'{hours} 小时')
    parts.append(f'{minutes:02d} 分' if hours or days else f'{minutes} 分')
    return ' '.join(parts)


# ===================== 服务 =====================

class UsageService(QObject):
    """陪伴时长计时员（进程内每个角色一个实例）"""

    def __init__(self, pet_name='yier', *, tick_interval_ms=TICK_MS, now_fn=None):
        if pet_name in _INSTANCES:
            raise RuntimeError(
                f'UsageService({pet_name}) 已存在，请复用同一实例')
        super().__init__()
        _INSTANCES[pet_name] = self

        self.pet_name = pet_name
        self._now_fn = now_fn or time.time
        self._data = load_data(pet_name)
        finalize_open_session(self._data, self._now_fn())
        if not self._data.get('first_use_ts'):
            self._data['first_use_ts'] = self._now_fn()
        self._last_ts = None     # 上次 tick 的墙钟；内存态，不落盘
        self._shutdown = False

        self._timer = QTimer(self)
        self._timer.setInterval(tick_interval_ms)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)   # 兜底，shutdown 幂等

    # ===================== 只读查询 =====================

    def today(self):
        """今天累计秒数（取整）"""
        day = date_key(self._now_fn())
        return int(self._data['daily'].get(day, {}).get('runtime_s', 0.0))

    def current_session(self):
        """当前会话记录副本；无会话返回空 dict"""
        sess = self._data['sessions'][-1] if self._data['sessions'] else None
        return dict(sess) if sess else {}

    def current_session_seconds(self):
        """当前会话已陪伴秒数（含尚未到 tick 的零头，供展示用）"""
        sess = self._data['sessions'][-1] if self._data['sessions'] else None
        if sess is None or sess.get('end_ts') is not None:
            return 0.0
        total = float(sess['runtime_s'])
        if self._last_ts is not None:
            gap = self._now_fn() - self._last_ts
            total += max(0.0, min(gap, float(TICK_S)))   # 与 tick 同样的睡眠保护
        return total

    def daily(self):
        """全部日聚合副本（窗口画柱状图用）"""
        return {k: dict(v) for k, v in self._data['daily'].items()}

    def first_use_ts(self):
        return float(self._data.get('first_use_ts') or 0.0)

    def raw_data(self):
        """整个数据 dict，调试与测试用"""
        return self._data

    # ===================== 生命周期 =====================

    def _on_tick(self):
        if self._shutdown:
            return
        now = self._now_fn()
        self._last_ts = advance(self._data, self._last_ts, now)
        self.flush()

    def flush(self):
        """幂等落盘；写失败（文件被杀软占用等）打警告不抛——数据在内存里，
        下一次 tick 或退出流程会再试，绝不能因为写盘把退出打断。"""
        try:
            save_data(self.pet_name, self._data)
        except OSError as e:
            print(f'[usage_service] {self.pet_name} 写盘失败，稍后重试: {e}')

    def shutdown(self):
        """退出：停表 + 补零头 + 收尾会话 + 落盘 + 注销单实例；幂等"""
        if self._shutdown:
            return
        self._shutdown = True
        self._timer.stop()

        now = self._now_fn()
        if self._last_ts is not None:
            gap = now - self._last_ts
            if 0 < gap:
                # 补最后一段不足一 tick 的零头；同样受 tick_s 上限约束
                credit = min(gap, float(TICK_S))
                _credit_interval(self._data, now - credit, now)

        sess = self._data['sessions'][-1] if self._data['sessions'] else None
        if sess is not None and sess.get('end_ts') is None:
            sess['end_ts'] = now
        self.flush()
        _INSTANCES.pop(self.pet_name, None)
