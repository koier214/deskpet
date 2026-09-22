"""固定任务规则持久化 —— JSON 读写 fixed_tasks.json

和 core/task_store.py 同一套写盘手法：先写临时文件再 os.replace，撞上杀软 /
索引服务占用目标文件时短暂重试。两个 store 各管自己的文件、各自原子写，不会互相
覆盖（没抽出公共 helper：task_store 那段是踩过坑的成品，动它风险大于收益）。

数据形状（读写都是整个 dict 进出，顶层未知键不会被写丢）：
    {
      "rules": [{"id": str, "text": str, "freq": "daily"|"weekday",
                 "minutes": int, "enabled": bool}],
      "generated": {"YYYY-MM-DD": ["rule_id", ...]}
    }
"""
import json
import os
import time

from core import settings

REPLACE_ATTEMPTS = 5
REPLACE_RETRY_DELAY_S = 0.02

DEFAULT_DATA = {
    "rules": [],
    "generated": {},
}


def _data_path(pet_name):
    return os.path.join(settings.BASEDIR, 'res', pet_name, 'fixed_tasks.json')


def _default_data():
    """深拷贝默认数据，避免多次调用共享同一个 dict"""
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data(pet_name):
    """读取 fixed_tasks.json；文件不存在、损坏或缺键时返回可用的默认数据"""
    path = _data_path(pet_name)
    if not os.path.exists(path):
        return _default_data()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # 文件坏了也要能启动，否则桌宠直接崩在构造阶段
        print(f'[fixed_task_store] {path} 读取失败，改用默认数据: {e}')
        return _default_data()
    if not isinstance(data, dict):
        return _default_data()
    data.setdefault('rules', [])
    data.setdefault('generated', {})
    return data


def save_data(pet_name, data):
    """写入 fixed_tasks.json（先写临时文件再 os.replace，避免半截文件）"""
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
