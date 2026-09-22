"""固定任务服务 —— 「每天自动追加」的唯一持有者

职责边界：
  - 规则（文本 / 频率 / 默认时长 / 启用开关）和「哪天已经生成过」的记账都在这里，
    落盘走 core/fixed_task_store.py 的 fixed_tasks.json；
  - 生成出来的实例是**普通任务**，由 TaskService 持有 —— 能勾完成、能挂倒计时、
    能改日期、能删。删掉当天那条不会补回来（generated 里记着账），这是
    「删了别自己又冒出来」的保证（2026-09-22 评审）；
  - 本服务只调 TaskService 的公开方法，不认识任何窗口，也不 import QtWidgets。

追加时机由 PetWindow 接：启动时一次 + TaskService 的 sig_day_changed（跨零点，
睡眠唤醒后一起补）。ensure_for() 幂等，重复调用不会生成第二条。
"""
from datetime import date

from PySide6.QtCore import QObject, Signal

from core.fixed_task_store import load_data, save_data
from logic.task_filters import today_str as _today_str

FREQ_DAILY = 'daily'
FREQ_WEEKDAY = 'weekday'
FREQ_LABELS = ((FREQ_DAILY, '每天'), (FREQ_WEEKDAY, '每个工作日'))
FREQ_TEXT = dict(FREQ_LABELS)

KEEP_DAYS = 7        # generated 只留最近 7 天，文件不会无限长
WEEKDAY_MAX = 5      # 工作日 = 周一~周五


class FixedTaskService(QObject):
    """固定任务规则 + 每天自动追加（进程内每个角色一个实例）"""

    sig_rules_changed = Signal()        # 规则增删改（含启用 / 暂停）
    sig_generated = Signal(str, int)    # 日期, 本次新追加的条数

    def __init__(self, task_service, pet_name=None, *, now_fn=None):
        super().__init__()
        self._service = task_service
        self.pet_name = pet_name or task_service.pet_name
        # 「现在」跟 TaskService 共用一支时钟：测试注入固定日期就能测工作日/跨天
        self._now_fn = now_fn or task_service.now
        self._data = load_data(self.pet_name)
        self._dirty = False
        self._normalize()

    # ===================== 只读 =====================

    def rules(self):
        """规则列表（活列表，视图约定只读）"""
        return self._data['rules']

    def rule(self, rule_id):
        for r in self._data['rules']:
            if r['id'] == rule_id:
                return r
        return None

    def enabled_count(self):
        return sum(1 for r in self._data['rules'] if r['enabled'])

    def due_rules(self, date_str):
        """某天该跑哪些规则：启用 + 频率匹配（每天 / 每个工作日）"""
        try:
            day = date.fromisoformat(date_str)
        except (TypeError, ValueError):
            return []
        is_workday = day.weekday() < WEEKDAY_MAX
        out = []
        for r in self._data['rules']:
            if not r['enabled']:
                continue
            if r['freq'] == FREQ_WEEKDAY and not is_workday:
                continue
            out.append(r)
        return out

    def generated_on(self, date_str):
        """某天已经追加过的 rule_id（被删掉的实例也算追加过）"""
        return list(self._data['generated'].get(date_str, []))

    def today_str(self):
        return _today_str(self._now_fn())

    # ===================== 规则增删改 =====================

    def add_rule(self, text, freq=FREQ_DAILY, minutes=25):
        """新增规则，返回 id；空白文本返回 None

        规则一落地就把今天该做的那条补进待办 —— 和页面上的说明一致，
        「今天加了明天才生效」会让用户以为没生效。
        """
        text = (text or '').strip()
        if not text:
            return None
        rule = {
            'id': self._new_rule_id(),
            'text': text,
            'freq': freq if freq in FREQ_TEXT else FREQ_DAILY,
            'minutes': max(0, int(minutes)),
            'enabled': True,
        }
        self._data['rules'].append(rule)
        self._mark_dirty(immediate=True)
        self.sig_rules_changed.emit()
        self.ensure_for()
        return rule['id']

    def set_enabled(self, rule_id, enabled):
        """启用 / 暂停一条规则；暂停后不再往后追加，已经生成的实例不动"""
        rule = self.rule(rule_id)
        if rule is None:
            return False
        rule['enabled'] = bool(enabled)
        self._mark_dirty(immediate=True)
        self.sig_rules_changed.emit()
        return True

    def remove_rule(self, rule_id):
        """删规则：已经追加出来的实例留着（那是当天要做的活），只是不再往后追加"""
        before = len(self._data['rules'])
        self._data['rules'] = [r for r in self._data['rules'] if r['id'] != rule_id]
        if len(self._data['rules']) == before:
            return False
        self._mark_dirty(immediate=True)
        self.sig_rules_changed.emit()
        return True

    # ===================== 每天自动追加 =====================

    def ensure_for(self, date_str=None):
        """把 date_str（默认今天）该有的固定任务补进待办，返回本次新增条数

        幂等：同一天同一规则只追加一次。generated 是「已经生成过」的记账，
        实例被删掉之后仍然记着，所以不会再补。
        """
        day = date_str or self.today_str()
        done = set(self._data['generated'].get(day, []))
        added = 0
        for rule in self.due_rules(day):
            if rule['id'] in done:
                continue
            self._service.add_task(rule['text'], rule['minutes'],
                                   due_date=day, fixed=True, rule_id=rule['id'])
            done.add(rule['id'])
            added += 1
        if added:
            self._data['generated'][day] = sorted(done)
            self._prune_generated()
            self._mark_dirty(immediate=True)
            self.sig_generated.emit(day, added)
        return added

    # ===================== 落盘 =====================

    def _mark_dirty(self, immediate=False):
        self._dirty = True
        if immediate:
            self.flush()

    def flush(self):
        """有脏数据才写盘；幂等。写失败保留脏标记，交给下一次重试"""
        if not self._dirty:
            return
        try:
            save_data(self.pet_name, self._data)
        except OSError as e:
            print(f'[fixed_task_service] {self.pet_name} 写盘失败，稍后重试: {e}')
            return
        self._dirty = False

    def shutdown(self):
        """退出：落盘（幂等）"""
        self._dirty = True
        self.flush()

    # ===================== 内部 =====================

    def _normalize(self):
        """把磁盘上的规则矫正成视图可以闭眼用的形状（容忍手工编辑过的 JSON）"""
        raw = self._data.get('rules')
        rules = []
        used = set()
        for r in (raw if isinstance(raw, list) else []):
            if not isinstance(r, dict):
                continue
            text = str(r.get('text') or '').strip()
            if not text:
                continue
            rid = str(r.get('id') or '')
            if not rid or rid in used:
                rid = self._alloc_id(used)
            used.add(rid)
            try:
                minutes = max(0, int(r.get('minutes', 25)))
            except (TypeError, ValueError):
                minutes = 25
            freq = r.get('freq')
            rules.append({
                'id': rid,
                'text': text,
                'freq': freq if freq in FREQ_TEXT else FREQ_DAILY,
                'minutes': minutes,
                'enabled': bool(r.get('enabled', True)),
            })

        raw_gen = self._data.get('generated')
        generated = {}
        if isinstance(raw_gen, dict):
            for day, ids in raw_gen.items():
                if isinstance(ids, list):
                    generated[str(day)] = sorted({str(i) for i in ids})
        self._data['rules'] = rules
        self._data['generated'] = generated
        self._prune_generated()
        if rules != raw or generated != raw_gen:
            self._mark_dirty()

    def _prune_generated(self):
        """generated 只留最近 KEEP_DAYS 天"""
        gen = self._data['generated']
        if len(gen) <= KEEP_DAYS:
            return
        for day in sorted(gen)[:-KEEP_DAYS]:
            gen.pop(day, None)

    @staticmethod
    def _alloc_id(used):
        """分配一个没被占用的规则 id（r1 / r2 …）"""
        seq = 0
        for rid in used:
            if rid.startswith('r') and rid[1:].isdigit():
                seq = max(seq, int(rid[1:]))
        while True:
            seq += 1
            candidate = f'r{seq}'
            if candidate not in used:
                return candidate

    def _new_rule_id(self):
        return self._alloc_id({r['id'] for r in self._data['rules']})
