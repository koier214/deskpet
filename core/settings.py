"""全局共享状态 —— 所有线程和 GUI 通过此模块读写当前帧数据"""
import os

# 项目根目录（core/ 的父目录）
BASEDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 当前显示的帧图片（由 Worker 线程写入，GUI 线程读取）
current_img = None
previous_img = None

# 帧锚点偏移（用于对齐不同尺寸的帧）
current_anchor = [0, 0]
previous_anchor = [0, 0]

# 角色缩放比例（运行时可变）
tunable_scale = 1.0

# WebSocket 通信配置（阶段四：一二 ↔ 布布跨电脑聊天）
# 下面四项都是**默认值**：启动时 core/app_config.apply_to_settings 会按
# 「命令行 > config.json > 默认值」覆盖。保留默认值是为了让直接 import settings
# 的脚本/测试行为不变。
WS_URL = 'ws://localhost:8765'   # 服务器地址（局域网时改成服务器 IP）
IDENTITY = 'yier'                # 本机身份：yier / bubu
PEER = 'bubu'                    # 通信对象身份
WS_TOKEN = ''                    # 共享密钥；空 = 服务器未启用鉴权，register 不带 token 字段
