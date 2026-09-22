"""今天 / 逾期 / 日历标记 —— 纯函数，零 Qt 依赖，时间可注入

为什么单开这一层（2026-09-18）：在此之前「今天」的判定散落在 8 处
（ui/ 6 处 + logic/ 2 处），既没法在测试里控制时间，也没法保证菜单、气泡、
日历三处口径一致。这里定义唯一口径，视图只消费结果。

两条约定：

1. **逾期是派生状态**：overdue = 有 due_date、due_date < 今天、且未完成。
   它不落盘、也不进 status —— status 的语义是「计时状态」（待做/进行中/暂停中/完成），
   逾期是「日期维度的欠账」，两者正交。所以「今天是哪天」变了不用迁移任何数据。

2. **日历格子三态**，优先级 逾期 > 未到期 > 已完成：

   | 状态 | 含义 | 颜色 |
   |---|---|---|
   | `overdue` | 这天有逾期未完成 | 红 |
   | `open`    | 这天有未完成但还没到期（含今天） | 棕 |
   | `done`    | 这天的任务全部完成 | 灰 |

   「有未完成」和「逾期」不是一回事：前者包含还没到日子的今天与将来。
"""
from datetime import date, datetime

DATE_FMT = '%Y-%m-%d'

# 日历三态 → 由高到低的优先级，合并同一天的多条任务时用
STATE_RANK = {None: 0, 'done': 1, 'open': 2, 'overdue': 3}

STATE_ORDER = ('overdue', 'open', 'done')


def _as_date(now=None):
    """把注入的「现在」统一成 date；None = 系统今天"""
    if now is None:
        return date.today()
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    raise TypeError(f'now 需要 date/datetime/None，收到 {type(now).__name__}')


def today_str(now=None):
    """今天 'YYYY-MM-DD'"""
    return _as_date(now).strftime(DATE_FMT)


def valid_date(value):
    """合法 'YYYY-MM-DD' 原样返回，其余（含 None/坏格式/非字符串）归 None（未安排）"""
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        datetime.strptime(value, DATE_FMT)
    except ValueError:
        return None
    return value


def is_done_today(task, now=None):
    """算不算「今天完成」：以 done_at 时间戳为准

    旧数据/手工编辑的数据没有 done_at（或类型不对）一律不算——
    几天前完成的任务不该一直挂在头顶的已完成区里。
    """
    ts = task.get('done_at')
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return False
    try:
        return datetime.fromtimestamp(ts).date() == _as_date(now)
    except (OverflowError, OSError, ValueError):
        return False


def is_overdue(task, now=None):
    """逾期：有归属日期、日期早于今天、且未完成

    未安排（due_date 为 None）与未来日期永不逾期；已完成的任务也不逾期。
    """
    if task.get('done'):
        return False
    due = valid_date(task.get('due_date'))
    if due is None:
        return False
    return due < today_str(now)


def overdue_days(task, now=None):
    """欠了几天；不逾期返回 0"""
    if not is_overdue(task, now):
        return 0
    due = datetime.strptime(valid_date(task['due_date']), DATE_FMT).date()
    return (_as_date(now) - due).days


def sort_overdue(tasks, now=None):
    """逾期任务排序：欠得最久的排最前

    按 due_date 升序（等价于按逾期天数降序）；同一天的保持原插入序 ——
    sorted 是稳定排序，不要改成 set/字典遍历破坏它。
    """
    return sorted(tasks, key=lambda t: valid_date(t.get('due_date')) or '')


def merge_state(current, incoming):
    """同一天多条任务合并成一个日历状态：逾期 > 未到期 > 已完成"""
    if STATE_RANK.get(incoming, 0) > STATE_RANK.get(current, 0):
        return incoming
    return current


def task_state(task, now=None):
    """单条任务对日历的贡献：overdue / open / done"""
    if is_overdue(task, now):
        return 'overdue'
    return 'done' if task.get('done') else 'open'


def date_state(tasks, date_str, now=None):
    """某一天在日历上的状态；那天没有任务返回 None"""
    state = None
    for t in tasks:
        if valid_date(t.get('due_date')) == date_str:
            state = merge_state(state, task_state(t, now))
    return state


def date_states(tasks, now=None):
    """{date_str: state}，日历标记一次算完；没有任务的日子不出现在结果里"""
    states = {}
    for t in tasks:
        d = valid_date(t.get('due_date'))
        if d is None:
            continue
        states[d] = merge_state(states.get(d), task_state(t, now))
    return states


def section_of(task, now=None):
    """气泡分区：'overdue' 逾期 / 'todo' 今天+未安排 / 'done' 今天完成 / None 不上气泡

    其他日期的任务不在气泡里（它们由菜单面板按天管理）。
    """
    if task.get('done'):
        return 'done' if is_done_today(task, now) else None
    if is_overdue(task, now):
        return 'overdue'
    due = valid_date(task.get('due_date'))
    if due is None or due == today_str(now):
        return 'todo'
    return None