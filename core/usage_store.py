"""使用时长数据持久化 —— JSON 读写 usage.json

完全镜像 task_store.py 的既有约定：原子写（.tmp + os.replace + 重试）、
文件损坏退回默认数据、写整 dict 不做键白名单过滤。
"""
import json
import os
import time

from core import settings

# Windows 上杀软/索引服务会短暂占住刚写完的文件，os.replace 偶发 ACCESS_DENIED
# （task_store 实测背靠背写盘约千分之一）。重试几次就能过去，最坏情况多花 ~100ms。
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_S = 0.02

SCHEMA = 1


def _data_path(pet_name):
    return os.path.join(settings.BASEDIR, 'res', pet_name, 'usage.json')


DEFAULT_DATA = {
    "schema": SCHEMA,
    "first_use_ts": 0.0,   # 第一次产生数据的时刻；0 = 还没有数据
    "daily": {},           # {"YYYY-MM-DD": {"runtime_s": float}}
    "sessions": [],        # [{"date", "start_ts", "end_ts", "runtime_s"}]
}


def _default_data():
    """深拷贝默认数据，避免多次调用共享同一个 dict"""
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data(pet_name):
    """读取 usage.json；文件不存在、损坏或 schema 不认时返回可用的默认数据"""
    path = _data_path(pet_name)
    if not os.path.exists(path):
        return _default_data()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # 数据文件坏了也要能启动，否则桌宠直接崩在构造阶段
        print(f'[usage_store] {path} 读取失败，改用默认数据: {e}')
        return _default_data()
    if not isinstance(data, dict) or data.get('schema') != SCHEMA:
        # 不认识的 schema 宁可重计也不读坏数据（未来迁移时在这里加分支）
        return _default_data()
    if not isinstance(data.get('first_use_ts'), (int, float)):
        data['first_use_ts'] = 0.0
    if not isinstance(data.get('daily'), dict):
        data['daily'] = {}
    if not isinstance(data.get('sessions'), list):
        data['sessions'] = []
    return data


def save_data(pet_name, data):
    """写入 usage.json（先写临时文件再 os.replace，避免半截文件）

    目标文件被别的进程短暂占用时重试；重试耗尽仍失败就抛给调用方决定怎么办。
    """
    path = _data_path(pet_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    for attempt in range(REPLACE_ATTEMPTS):
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(payload)
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_DELAY_S)
