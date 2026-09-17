"""加载 pet_conf.json 和 act_conf.json，构建 PetConfig + Act 对象"""
import json
import os
import glob
import re

from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

from core import settings


class Act:
    """单个动画动作：一组帧图片 + 播放参数"""
    def __init__(self, images, act_name=None, act_num=1, need_move=False,
                 direction=None, frame_move=10, frame_refresh=0.04, anchor=(0, 0)):
        self.images = images              # list[QPixmap]
        self.act_name = act_name          # 动作名
        self.act_num = act_num            # 图片序列循环次数
        self.need_move = need_move        # 是否带动画位移
        self.direction = direction        # 位移方向 left/right/up/down
        self.frame_move = frame_move      # 单帧位移像素
        self.frame_refresh = frame_refresh # 每帧停留秒数
        self.anchor = anchor              # 锚点偏移 [x, y]

    @classmethod
    def init_act(cls, conf_param, pic_dict, scale, pet_name):
        """从 act_conf.json 的一个条目创建 Act 对象"""
        images_key = conf_param['images']
        img_dir = os.path.join(settings.BASEDIR, 'res', pet_name, 'action')

        # 按数字索引排序找到所有匹配帧
        list_images = glob.glob(os.path.join(img_dir, f'{images_key}_*.png'))
        pattern = re.compile(rf"^{re.escape(images_key)}_(\d+)\.png$")
        matching_idx = sorted(
            [pattern.match(os.path.basename(f)).group(1) for f in list_images
             if pattern.match(os.path.basename(f))],
            key=lambda x: int(x)
        )

        # 从 pic_dict 取出对应的 QPixmap
        imgs = [pic_dict[f"{images_key}_{i}"] for i in matching_idx]

        # 缩放
        if scale != 1.0:
            imgs = [i.scaled(int(i.width() * scale), int(i.height() * scale),
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    for i in imgs]

        return cls(
            images=imgs,
            act_name=conf_param.get('act_name'),
            act_num=conf_param.get('act_num', 1),
            need_move=conf_param.get('need_move', False),
            direction=conf_param.get('direction'),
            frame_move=conf_param.get('frame_move', 10) * scale,
            frame_refresh=conf_param.get('frame_refresh', 0.5),
            anchor=conf_param.get('anchor', [0, 0]),
        )


class PetConfig:
    """宠物角色配置：尺寸、缩放、各动作映射"""
    def __init__(self):
        self.petname = None
        self.width = 128
        self.height = 128
        self.scale = 1.0
        self.interact_speed = 20       # 交互线程定时器间隔 (ms)
        self.default = None            # 默认待机 Act
        self.drag = None               # 拖拽时 Act
        self.patpat = None             # 点击反馈 Act
        self.random_act = []           # list[list[Act]] 随机动作组
        self.act_prob = []             # 各随机动作的归一化概率
        self.act_name = []             # 随机动作名列表

    @classmethod
    def init_config(cls, pet_name):
        """从 res/{pet_name}/ 加载完整角色配置"""
        base_dir = os.path.join(settings.BASEDIR, 'res', pet_name)
        conf_path = os.path.join(base_dir, 'pet_conf.json')

        with open(conf_path, 'r', encoding='utf-8') as f:
            conf = json.load(f)

        o = cls()
        o.petname = pet_name
        o.scale = conf.get('scale', 1.0)
        o.width = conf.get('width', 128) * o.scale
        o.height = conf.get('height', 128) * o.scale
        o.interact_speed = conf.get('interact_speed', 0.02) * 1000

        # 加载所有帧图片
        pic_dict = _load_all_pic(pet_name)

        # 加载所有动作定义
        act_path = os.path.join(base_dir, 'act_conf.json')
        with open(act_path, 'r', encoding='utf-8') as f:
            act_conf = json.load(f)
        act_dict = {k: Act.init_act(v, pic_dict, o.scale, pet_name)
                    for k, v in act_conf.items()}

        # 基础动作映射
        o.default = act_dict[conf['default']]
        o.drag = act_dict[conf['drag']]

        # 点击动作 -> 直接映射到 Act（不区分 HP 层级）
        pat_name = conf.get('patpat', 'default')
        o.patpat = act_dict[pat_name]

        # 随机动作池
        random_acts = []
        act_probs = []
        act_names = []
        for ra in conf.get('random_act', []):
            random_acts.append([act_dict[a] for a in ra['act_list']])
            act_probs.append(ra.get('act_prob', 0.2))
            act_names.append(ra.get('name', None))

        o.random_act = random_acts
        total = sum(act_probs)
        o.act_prob = [p / total if total > 0 else 0 for p in act_probs]
        o.act_name = act_names

        return o


def _load_all_pic(pet_name):
    """加载 res/{pet_name}/action/ 下所有 PNG 为 QPixmap 字典"""
    img_dir = os.path.join(settings.BASEDIR, 'res', pet_name, 'action')
    images = os.listdir(img_dir)
    pic_dict = {}
    for fname in images:
        if fname.endswith('.png'):
            key = fname.replace('.png', '')
            pix = QPixmap()
            pix.load(os.path.join(img_dir, fname))
            pic_dict[key] = pix
    return pic_dict
