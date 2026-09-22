"""一二菜单的视觉主题 —— 纯 QSS，只换皮不动逻辑

设计基调：暖奶油底 + 棕（#B08968，与日历"未到期"圆点 CAL_DOT_OPEN、柱状图
BAR_COLOR、聊天气泡同色系）+ 白色圆角卡片。数据流 / 信号契约 / service 一行不碰。

用法：MenuPanel 构造末尾调 `theme.apply(self)`；子控件的 objectName 在各自
创建处设置（entryBtn / entryBtnAlert / batchBtn / addBtn / taskInput /
taskSelect / taskScroll / dayHeader / daySub / rowDue / rowTag / rowDel /
taskRow / taskRowOverdue / ruleRow / ruleRowOff / ruleMark / ruleFreq /
ruleEmpty / ruleBtn / ruleBtnOn / ruleNote / menuTabs / menuTabBar）。
"""
from string import Template

from PySide6.QtCore import Qt

BG = '#FAF7F2'           # 面板底：暖奶油
CARD = '#FFFFFF'         # 卡片 / 输入框底
CARD_BORDER = '#EBE1D4'  # 卡片描边
ACCENT = '#B08968'       # 主色：棕（与 CAL_DOT_OPEN / BAR_COLOR 同一色）
ACCENT_DARK = '#96704F'
ACCENT_SOFT = '#F4EBE1'  # 主色浅底：hover / 选中 / 进行中计时 chip
TEXT = '#3E342B'
TEXT_DIM = '#9A8B7B'

# 账号标签的分区配色（2026-09-22 起）。规则只有一条：**一个颜色只许有一个意思**。
#   浅暖灰   = 结构（区块标题条），不承载含义
#   极浅暖   = 「这是一条记录」（连接码框、申请行、联系人行）
#   暖棕浅底 = **只**给「需要你动手」的那一块标题条，全页唯一的强调色
# 改之前先读设计稿第 6 节：连接码框曾经用过 ACCENT_SOFT，和「待你确认的申请」
# 标题条撞成同一个色号 —— 两件不相干的事看起来像同一类，评审时被指出来了。
SECTION_HEAD_BG = '#F8F2E9'   # 区块标题条
INNER_BG = BG                 # 区块里"一行东西"的底
ALERT_HEAD_BG = ACCENT_SOFT   # 唯一强调色：需要你动手的那块标题条

# 悬浮气泡（待办气泡 / 聊天气泡 / 输入气泡）：半透明暖白，桌面任何壁纸上都融得进去
BUBBLE_BG = 'rgba(255, 252, 247, 0.94)'
BUBBLE_BORDER = '#E3D5C3'

# 语义色：状态不改含义，只统一圆角与中性灰的暖调
DONE_GREEN = '#2E7D32'
DONE_GREEN_BG = '#E8F5E9'
RUN_RED = '#C62828'
RUN_RED_BG = '#FFEBEE'
PAUSE_ORANGE = '#E65100'
PAUSE_ORANGE_BG = '#FFF3E0'
NEUTRAL_BG = '#F3EEE6'
NEUTRAL_TEXT = '#6B6156'

# 顺延标识（2026-09-18 待办改版，2026-09-22 起统一叫「顺延」）：
# 行首红条、行内「顺延 N 天」、日历顺延点。
# 和「进行中」共用同一支红——不新增色号，靠位置与文字区分语义。
OVERDUE = RUN_RED
OVERDUE_BG = RUN_RED_BG
OVERDUE_BORDER = '#F0D2D2'   # 顺延按钮/入口的浅红描边

# 日历三态圆点：对应 logic/task_filters.py 的 open / overdue / done
CAL_DOT_OPEN = ACCENT
CAL_DOT_OVERDUE = RUN_RED
CAL_DOT_DONE = '#D8CFC2'
CAL_DOT = {'open': CAL_DOT_OPEN, 'overdue': CAL_DOT_OVERDUE, 'done': CAL_DOT_DONE}

# 头顶气泡行首圆点：归属今天=棕，其他任务=暖灰（2026-09-18 评审：气泡用圆点分色）
DOT_TODAY = ACCENT
DOT_UNDATED = '#C2B5A5'

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
/* 待办页三个快捷入口（今天 / 顺延 / 其他任务）：胶囊按钮，选中=棕底 */
QPushButton#entryBtn, QPushButton#entryBtnAlert {
    background: $CARD; color: $NEUTRAL_TEXT; border: 1px solid $CARD_BORDER;
    border-radius: 11px; padding: 4px 13px; font-size: 12px;
}
QPushButton#entryBtn:hover, QPushButton#entryBtnAlert:hover { border-color: $ACCENT; }
QPushButton#entryBtn:checked {
    background: $ACCENT_SOFT; border-color: $ACCENT;
    color: $ACCENT_DARK; font-weight: bold;
}
/* 有顺延时「顺延」入口整体转红，扫一眼就知道欠着账 */
QPushButton#entryBtnAlert {
    background: #FFF7F7; border-color: $OVERDUE_BORDER; color: $OVERDUE;
}
QPushButton#entryBtnAlert:checked {
    background: $OVERDUE_BG; border-color: $OVERDUE; color: $OVERDUE; font-weight: bold;
}
QPushButton#batchBtn {
    background: $PAUSE_ORANGE_BG; border: 1px solid #F0D4B4;
    color: $PAUSE_ORANGE; border-radius: 8px; padding: 4px 10px;
    font-size: 11px; font-weight: bold;
}
QPushButton#batchBtn:hover { background: #FFE7CC; border-color: $PAUSE_ORANGE; }
/* 输入行右侧「添加」按钮：主色实底。回车和它走的是同一条路 */
QPushButton#addBtn {
    background: $ACCENT; border: 1px solid $ACCENT; color: #FFFFFF;
    border-radius: 8px; padding: 5px 14px; font-weight: bold; font-size: 12px;
}
QPushButton#addBtn:hover { background: $ACCENT_DARK; border-color: $ACCENT_DARK; }

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
/* 顺延行行首是一条 3px 红竖条；普通行用等宽透明竖条占位，两者左边才对齐 */
QWidget#taskRow, QWidget#taskRowOverdue {
    background: $CARD; border: 1px solid $CARD_BORDER;
    border-left: 3px solid transparent; border-radius: 10px;
}
QWidget#taskRowOverdue { border-left: 3px solid $OVERDUE; }
QWidget#taskRow:hover, QWidget#taskRowOverdue:hover { border-color: $ACCENT; }
QWidget#taskRowOverdue:hover { border-left: 3px solid $OVERDUE; }
QWidget#taskRow QLabel, QWidget#taskRowOverdue QLabel { color: $TEXT; }
QWidget#taskRow QPushButton, QWidget#taskRowOverdue QPushButton {
    padding: 3px 8px; border-radius: 6px;
}
/* 选择器带上 taskRow 前缀：不加就会被上面那条 QLabel 通配压成黑字
   （Qt 的 QSS 按 CSS2.1 算特异性，后代选择器比单独一条 #id 更「重」） */
QWidget#taskRow QLabel#rowDue, QWidget#taskRowOverdue QLabel#rowDue {
    color: $OVERDUE; font-size: 11px; font-weight: bold;
}
/* 「固定」徽章：贴在任务文字后面，比正文字号小一档 */
QWidget#taskRow QLabel#rowTag, QWidget#taskRowOverdue QLabel#rowTag {
    background: $ACCENT_SOFT; color: $ACCENT_DARK;
    border: none; border-radius: 6px; padding: 1px 6px; font-size: 10px;
}
QPushButton#rowDel {
    padding: 0; border: none; background: transparent;
    color: #B6A897; font-size: 12px;
}
QPushButton#rowDel:hover { background: $OVERDUE_BG; color: $OVERDUE; border: none; }

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

/* ---------- 下拉（输入行的归属 / 时长） ---------- */
QComboBox#taskSelect {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 8px;
    padding: 5px 8px; color: $NEUTRAL_TEXT; font-size: 11px;
}
QComboBox#taskSelect:hover { border-color: $ACCENT; }
QComboBox#taskSelect QAbstractItemView {
    background: $CARD; border: 1px solid $CARD_BORDER; color: $TEXT;
    selection-background-color: $ACCENT_SOFT; selection-color: $TEXT; outline: none;
}

/* ---------- 标题、图例与统计页 ---------- */
QLabel#dayHeader { color: $TEXT; font-size: 13px; font-weight: bold; }
QLabel#daySub { color: $TEXT_DIM; font-size: 11px; }
QLabel#legendText { color: $TEXT_DIM; font-size: 11px; }
QWidget#usageTab { background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 10px; }

/* ---------- 固定任务页（2026-09-22）：说明条 + 规则行 ---------- */
QLabel#ruleNote {
    background: $ACCENT_SOFT; color: $ACCENT_DARK;
    border-radius: 8px; padding: 6px 9px; font-size: 11px;
}
QWidget#ruleRow, QWidget#ruleRowOff {
    background: $CARD; border: 1px solid $CARD_BORDER; border-radius: 10px;
}
QWidget#ruleRowOff { background: #FCFBF9; border-color: #F0EAE0; }
QWidget#ruleRow:hover, QWidget#ruleRowOff:hover { border-color: $ACCENT; }
QWidget#ruleRow QLabel, QWidget#ruleRowOff QLabel { color: $TEXT; }
QWidget#ruleRowOff QLabel#ruleText { color: $TEXT_DIM; }
QWidget#ruleRow QLabel#ruleMark, QWidget#ruleRowOff QLabel#ruleMark {
    color: $ACCENT; font-size: 12px;
}
QWidget#ruleRow QLabel#ruleText, QWidget#ruleRowOff QLabel#ruleText { font-size: 12px; }
QWidget#ruleRow QLabel#ruleFreq, QWidget#ruleRowOff QLabel#ruleFreq {
    color: $TEXT_DIM; font-size: 11px;
}
QLabel#ruleEmpty { color: $TEXT_DIM; font-size: 12px; }
QPushButton#ruleBtn, QPushButton#ruleBtnOn {
    background: $NEUTRAL_BG; color: $NEUTRAL_TEXT;
    border: none; border-radius: 6px; padding: 2px 0; font-size: 11px;
}
QPushButton#ruleBtnOn { background: $ACCENT_SOFT; color: $ACCENT_DARK; font-weight: bold; }
QPushButton#ruleBtn:hover, QPushButton#ruleBtnOn:hover { background: $ACCENT_SOFT; }

/* ---------- 账号标签的分区 ---------- */
/* 注意：普通 QWidget 子类要吃 QSS 背景，必须自己开 WA_StyledBackground，
   否则背景根本画不出来（见 apply() 里 usageTab 的既有做法）。 */
QWidget#sectionHead { background: $SECTION_HEAD_BG; border: none; }
QWidget#alertHead { background: $ALERT_HEAD_BG; border: none; }
QWidget#innerRow {
    background: $INNER_BG; border: 1px solid $CARD_BORDER; border-radius: 9px;
}
""")

MENU_QSS = _TPL.substitute(
    BG=BG, CARD=CARD, CARD_BORDER=CARD_BORDER, ACCENT=ACCENT,
    ACCENT_DARK=ACCENT_DARK, ACCENT_SOFT=ACCENT_SOFT, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
    NEUTRAL_TEXT=NEUTRAL_TEXT, OVERDUE=OVERDUE, OVERDUE_BG=OVERDUE_BG,
    NEUTRAL_BG=NEUTRAL_BG,
    OVERDUE_BORDER=OVERDUE_BORDER, PAUSE_ORANGE=PAUSE_ORANGE,
    PAUSE_ORANGE_BG=PAUSE_ORANGE_BG,
    SECTION_HEAD_BG=SECTION_HEAD_BG, INNER_BG=INNER_BG, ALERT_HEAD_BG=ALERT_HEAD_BG,
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
