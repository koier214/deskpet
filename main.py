"""一二桌宠 — 极简入口

配置优先级：命令行 > config.json > core/app_config.DEFAULTS
用法示例：
  python main.py                                  # 零配置，等价于今天的 yier + localhost:8765
  python main.py --server ws://192.168.1.5:8765   # 连局域网里的服务器
  python main.py --identity bubu --pet-name bubu  # 本机跑布布端
"""
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.app_config import ConfigError, apply_to_settings, load_config
from ui.pet_window import PetWindow


def main():
    # 必须在 QApplication 之前跑完：配置错了就该在开窗之前退出
    try:
        cfg = load_config(sys.argv[1:])
    except ConfigError as e:
        print(f'[config] {e}', file=sys.stderr)
        sys.exit(2)
    apply_to_settings(cfg)

    app = QApplication(sys.argv)   # 仍传原始 argv：Qt 会忽略它不认识的参数，现状即如此
    app.setQuitOnLastWindowClosed(False)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)

    window = PetWindow(pet_name=cfg['pet_name'])
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
