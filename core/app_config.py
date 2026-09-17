"""应用配置装载：命令行 > config.json > 代码内置默认值

设计约束：
  1. 只 import 标准库 + core.settings（后者也只依赖 os），**不碰 Qt**，方便无头测试
  2. load_config 只用 ConfigError 报「配置内容」问题，自己绝不 sys.exit；致命错误的
     stderr 输出和 sys.exit(2) 由 main.py 负责。两个例外：(a) argparse 遇到非法命令行
     开关会自己打印 usage 并 exit(2)，这是想要的行为，main.py 不必捕获；(b) 未知键的
     警告由 _read_config_file 直接打到 stderr（非致命，不值得为它加返回值）
  3. apply_to_settings 是全项目**唯一**修改 settings 配置项的地方
"""
import argparse
import json
import os
import sys

from core import settings

DEFAULTS = {
    'pet_name': 'yier',
    'identity': 'yier',
    'peer': None,                    # None = 按 PEER_MAP 自动推导
    'ws_url': 'ws://localhost:8765',
    'token': '',
}

# identity -> peer 的推导表。加第三个角色时往这里加一行即可
PEER_MAP = {'yier': 'bubu', 'bubu': 'yier'}


class ConfigError(Exception):
    """配置错误：由 main.py 捕获后打印并 sys.exit(2)"""


def build_arg_parser():
    """所有 default=None —— 这样「没传」和「传了空串」可区分，三级优先级才成立

    开关的 dest 一律和 DEFAULTS 的键同名（--server 用 dest='ws_url' 对齐），
    load_config 直接遍历 DEFAULTS 取值，不另立映射表当第二份白名单。
    """
    p = argparse.ArgumentParser(prog='main.py', description='一二桌宠')
    p.add_argument('--pet-name', default=None,
                   help='角色名，决定 res/<name>/ 与 tasks.json 的位置（默认 yier）')
    p.add_argument('--identity', default=None,
                   help='本机身份：yier / bubu（默认 yier）')
    p.add_argument('--peer', default=None,
                   help='通信对象身份；不填则按 identity 自动推导')
    p.add_argument('--server', dest='ws_url', default=None,
                   help='WS 服务器地址，如 ws://192.168.1.5:8765')
    p.add_argument('--token', default=None,
                   help='WS 共享密钥；留空表示服务器未启用鉴权。命令行对本机其它进程可见，'
                        '长期密钥更适合写在 config.json 里')
    p.add_argument('--config', default=None,
                   help='配置文件路径（默认 <项目根>/config.json）')
    return p


def default_config_path():
    return os.path.join(settings.BASEDIR, 'config.json')


def _read_config_file(path, optional=True):
    """读 config.json。

    文件不存在：optional=True → 返回 {}（零配置必须能跑）；optional=False → ConfigError
    （只有用户用 --config 亲自点名的文件才这样：路径拼错却静默退回默认值一样难查）。
    JSON 损坏 / 顶层不是对象 → 抛 ConfigError。**绝不静默降级**：配置坏了却用
    默认值会连错服务器、顶错身份，比直接崩掉难查得多。
    """
    if not os.path.exists(path):
        if optional:
            return {}
        raise ConfigError(f'配置文件不存在：{path}')
    try:
        # utf-8-sig：这个文件要用户手打，Windows 记事本 / PowerShell 5.1 会带 BOM，
        # 用 utf-8-sig 则带 BOM 和不带 BOM 都能正确读
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f'配置文件读取失败 {path}: {e}')
    if not isinstance(data, dict):
        raise ConfigError(f'配置文件顶层必须是 JSON 对象（{{...}}），实际是 {type(data).__name__}: {path}')

    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        print(f'[config] 警告：{path} 里有未知键 {unknown}，已忽略（检查一下是不是拼错了）',
              file=sys.stderr)
    return {k: v for k, v in data.items() if k in DEFAULTS}


def _validate(cfg, path):
    """校验合并结果的值类型，坏值一律 ConfigError，绝不悄悄 str() 或留成 None

    这些值流到下游全是**静默**故障：ws_url=None 让 QUrl(None) 变成空 URL，WS 客户端
    无限重连却打不出原因；identity=None 会发出畸形的 register 包；token={"a":1} 会
    变成 Python repr 字符串，永远匹配不上服务端的密钥。
    """
    for key in ('pet_name', 'identity', 'ws_url'):
        val = cfg[key]
        if not isinstance(val, str) or not val.strip():
            raise ConfigError(f'配置项 {key} 必须是非空字符串，实际是 {val!r}（{path}）')
    # peer / token 允许「不填」：peer 是 None/'' 表示走推导，token 是 None 表示不设密钥
    if cfg['peer'] not in (None, '') and not isinstance(cfg['peer'], str):
        raise ConfigError(f'配置项 peer 必须是字符串或留空，实际是 {cfg["peer"]!r}（{path}）')
    if cfg['token'] is not None and not isinstance(cfg['token'], str):
        raise ConfigError(f'配置项 token 必须是字符串或留空，实际是 {cfg["token"]!r}（{path}）')


def _resolve_peer(cfg):
    """peer 没填就按 PEER_MAP 推导；推不出来就报错，不猜通信对象"""
    # 故意用真值判断：''/null 都算「没填」—— 空 peer 到下游没法路由，推导比放行安全
    if cfg['peer']:
        return cfg['peer']
    identity = cfg['identity']
    if identity not in PEER_MAP:
        raise ConfigError(
            f"无法从 identity='{identity}' 推导通信对象。已知身份只有 {sorted(PEER_MAP)}；"
            f"请在 config.json 里写 \"peer\": \"...\"，或启动时加 --peer ..."
        )
    return PEER_MAP[identity]


def load_config(argv, config_path=None):
    """三级合并，返回校验过、补全 peer、token 归一化后的完整 dict。

    argv: 命令行参数列表（main.py 传 sys.argv[1:]）
    config_path: 只为测试注入用；None 时按 --config，再退回 <项目根>/config.json
    """
    args = build_arg_parser().parse_args(argv)
    path = config_path or args.config or default_config_path()

    cfg = dict(DEFAULTS)
    # 只有用户用 --config 点名的文件才必须存在，其余情况缺席即「零配置」
    cfg.update(_read_config_file(path, optional=(args.config is None)))

    for key in DEFAULTS:               # --config 不在 DEFAULTS 里，天然被跳过
        val = getattr(args, key, None)
        if val is not None:            # 没传（None）不覆盖 config.json 的值
            cfg[key] = val

    _validate(cfg, path)
    cfg['peer'] = _resolve_peer(cfg)
    if cfg['token'] is None:           # JSON 里写 null 等同「不设密钥」
        cfg['token'] = ''
    return cfg


def apply_to_settings(cfg):
    """把配置写回 settings 模块变量 —— 全项目唯一修改这四个配置项的地方"""
    settings.WS_URL = cfg['ws_url']
    settings.IDENTITY = cfg['identity']
    settings.PEER = cfg['peer']
    settings.WS_TOKEN = cfg['token']
