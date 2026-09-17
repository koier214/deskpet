"""一二菜单的视觉主题 —— 纯 QSS，只换皮不动逻辑

设计基调：暖奶油底 + 棕（#B08968，与日历标记色 MARK_COLOR、柱状图 BAR_COLOR、
聊天气泡同色系）+ 白色圆角卡片。数据流 / 信号契约 / service 一行不碰。

用法：MenuPanel 构造末尾调 `theme.apply(self)`；子控件的 objectName 在各自
创建处设置（undatedBtn / addBtn / taskInput / taskScroll / dayHeader /
menuTabs / menuTabBar / taskRow）。
"""
from string import Template

from PySide6.QtCore import Qt

BG = '#FAF7F2'           # 面板底：暖奶油
CARD = '#FFFFFF'         # 卡片 / 输入框底
CARD_BORDER = '#EBE1D4'  # 卡片描边
ACCENT = '#B08968'       # 主色：棕（与 MARK_COLOR / BAR_COLOR 同一色）
ACCENT_DARK = '#96704F'
ACCENT_SOFT = '#F4EBE1'  # 主色浅底：hover / 选中 / 进行中计时 chip
TEXT = '#3E342B'
TEXT_DIM = '#9A8B7B'

# 悬浮气泡（待办气泡 / 聊天气泡 / 输入气泡）：半透明暖白，桌面任何壁纸上都融得进去
BUBBLE_BG = 'rgba(255, 252, 247, 0.94)'
BUBBLE_BORDER = '#E3D5C3'

# 语义色：状态不改含义，只统一圆角与中性灰的暖调
DONE_GREEN = '#2E7D32'
RUN_RED = '#C62828'
RUN_RED_BG = '#FFEBEE'
PAUSE_ORANGE = '#E65100'
PAUSE_ORANGE_BG = '#FFF3E0'
NEUTRAL_BG = '#F3EEE6'
NEUTRAL_TEXT = '#6B6156'

# 头顶卡片统一规格（聊天气泡栈 / 待办气泡 / 输入气泡共用）：表面 + 标题色 + 正文色。
# 2026-09-14 起头顶所有气泡都从这张表取色，保证风格统一。
CARD_SPEC = {
    'peer':   {'bg': ACCENT,    'border': None,
               'head': '#FFE8D6',     'body': '#FFFFFF'},
    'me':     {'bg': CARD,      'border': CARD_BORDER,
               'head': ACCENT_DARK,   'body': TEXT},
    'notice': {'bg': BUBBLE_BG, 'border': BUBBLE_BORDER,
               'head': TEXT_DIM,      'body': TEXT},
}
CARD_SPEC['panel'] = CARD_SPEC['me']   # 待办/输入气泡：和白色消息卡同一张脸

_TPL = Template("""
QWidget#menuPanel { background: $BG; }

/* ---------- 标签页 ---------- */
QTabWidget#menuTabs::pane { border: none; background: transparent; }
QTabBar#menuTabBar::tab {
    background: transparent; color: $TEXT_DIM;
    padding: 8px 18px; border: none; border-bottom: 2px solid transparent;
    font-size: 13px; font-weight: bold;
}
QTabBar#menuTabBar::tab:selected { color: $ACCENT_DARK; border-bottom: 2px solid $ACCENT; }
QTabBar#menuTabBar::tab:hover:!selected { color: $TEXT; }

/* ---------- 日历 ---------- */
QCalendarWidget {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 10px;
}
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background: $ACCENT_SOFT;
    border-top-left-radius: 10px; border-top-right-radius: 10px;
    padding: 2px;
}
QCalendarWidget QToolButton {
    color: $TEXT; font-weight: bold; border-radius: 6px; padding: 4px 8px;
}
QCalendarWidget QToolButton:hover { background: #E9DCCB; }
QCalendarWidget QToolButton#qt_calendar_prevmonth,
QCalendarWidget QToolButton#qt_calendar_nextmonth { padding: 4px 12px; }
QCalendarWidget QLineEdit#qt_calendar_yearedit {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 6px;
    padding: 2px 6px;
}
QCalendarWidget QTableView#qt_calendar_calendarview {
    background: $CARD; border: none; outline: none;
    selection-background-color: $ACCENT; selection-color: #FFFFFF;
}
QCalendarWidget QTableView#qt_calendar_calendarview::item {
    padding: 3px; border: none; background: transparent;
}
QCalendarWidget QHeaderView::section {
    background: transparent; border: none;
    color: $TEXT_DIM; padding: 4px 0; font-weight: bold;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background: $CARD; color: $TEXT; border: 1px solid $CARD_BORDER;
    border-radius: 8px; padding: 5px 14px; font-size: 12px;
}
QPushButton:hover { background: $ACCENT_SOFT; border-color: $ACCENT; }
QPushButton:pressed { background: #EADFD0; }
QPushButton#addBtn {
    background: $ACCENT; border-color: $ACCENT; color: #FFFFFF; font-weight: bold;
}
QPushButton#addBtn:hover { background: $ACCENT_DARK; border-color: $ACCENT_DARK; }
QPushButton#undatedBtn:checked {
    background: $ACCENT_SOFT; border-color: $ACCENT;
    color: $ACCENT_DARK; font-weight: bold;
}

/* ---------- 输入框 ---------- */
QLineEdit#taskInput {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 8px;
    padding: 6px 10px; color: $TEXT; selection-background-color: $ACCENT;
}
QLineEdit#taskInput:focus { border-color: $ACCENT; }

/* ---------- 列表与滚动条 ---------- */
QScrollArea#taskScroll { background: transparent; border: none; }
QWidget#taskScrollContent, QWidget#taskScrollViewport { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: #DCCDBB; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: $ACCENT; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 0; }

/* ---------- 任务行卡片 ---------- */
QWidget#taskRow {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 10px;
}
QWidget#taskRow:hover { border-color: $ACCENT; }
QWidget#taskRow QLabel { color: $TEXT; }
QWidget#taskRow QPushButton { padding: 3px 8px; border-radius: 6px; }

/* ---------- 复选框：圆形 ---------- */
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 8px;
    border: 1.5px solid #CDBBA6; background: $CARD;
}
QCheckBox::indicator:hover { border-color: $ACCENT; }
QCheckBox::indicator:checked { background: $ACCENT; border-color: $ACCENT; }

/* ---------- 右键菜单 ---------- */
QMenu {
    background: $CARD; border: 1px solid $CARD_BORDER;
    border-radius: 10px; padding: 6px;
}
QMenu::item { padding: 6px 26px 6px 14px; border-radius: 6px; color: $TEXT; }
QMenu::item:selected { background: $ACCENT_SOFT; }
QMenu::item:disabled { color: #B9AC9C; }
QMenu::separator { height: 1px; background: $CARD_BORDER; margin: 4px 10px; }

/* ---------- 标题与统计页 ---------- */
QLabel#dayHeader { color: $TEXT; font-size: 13px; font-weight: bold; }
QWidget#usageTab { background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 10px; }
""")

MENU_QSS = _TPL.substitute(
    BG=BG, CARD=CARD, CARD_BORDER=CARD_BORDER, ACCENT=ACCENT,
    ACCENT_DARK=ACCENT_DARK, ACCENT_SOFT=ACCENT_SOFT, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
)


def rgba(color, alpha=1.0):
    """主题色（#hex 或 rgba(...)）× 透明度 → rgba() 串；气泡淡出时逐帧调 alpha"""
    c = color.strip()
    if c.startswith('#'):
        r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
        base = 1.0
    else:
        nums = c[c.index('(') + 1:c.index(')')].split(',')
        r, g, b = (int(float(x)) for x in nums[:3])
        base = float(nums[3]) if len(nums) > 3 else 1.0
    return f'rgba({r}, {g}, {b}, {round(base * alpha, 3)})'


def surface_qss(kind, object_name, alpha=1.0):
    """卡片表面（底色 + 描边 + 圆角 10px）的 QSS 块"""
    spec = CARD_SPEC[kind]
    border = (f'border: 1px solid {rgba(spec["border"], alpha)};'
              if spec['border'] else '')
    return (f'#{object_name} {{ background: {rgba(spec["bg"], alpha)}; '
            f'{border} border-radius: 10px; }}')


def card_qss(kind, alpha=1.0):
    """整张消息卡（表面 + 加粗标题 + 换行正文）的 QSS，淡出时整体调 alpha"""
    spec = CARD_SPEC[kind]
    return f'''
        {surface_qss(kind, 'card', alpha)}
        #head {{
            border: none; font-size: 12px; font-weight: bold;
            color: {rgba(spec['head'], alpha)};
        }}
        #body {{
            border: none; font-size: 14px;
            color: {rgba(spec['body'], alpha)};
        }}
    '''


def apply(panel):
    """把主题挂到 MenuPanel 上（stylesheet 会自动级联到所有子控件）"""
    panel.setObjectName('menuPanel')
    panel.setStyleSheet(MENU_QSS)
    usage = getattr(panel, '_usage_tab', None)
    if usage is not None:
        usage.setObjectName('usageTab')
        # 普通 QWidget 子类要吃 QSS 背景必须开这个属性
        usage.setAttribute(Qt.WA_StyledBackground, True)
        lay = usage.layout()
        if lay is not None:
            lay.setContentsMargins(14, 12, 14, 12)
