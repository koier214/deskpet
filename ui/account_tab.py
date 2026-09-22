# -*- coding: utf-8 -*-
"""「账号」标签页 —— 登录、我的连接码、连接别人、同意别人的申请、已连接的人

纯视图：只发信号（用户想干什么）、只收信号（服务器回了什么），
**不碰网络、不读写 config.json** —— 那是 PetWindow 与 WsClient 的活。
分层规矩见 AGENTS.md §5；配色规矩见 ui/theme.py 顶部那段注释。

界面按 YierBubu/docs/账号界面草图.html：
一整块连续的板子，各区块之间**不留白**、只用一条细线分隔；
每个区块都是「浅暖色标题条 + 白底内容」，五个区块同一套长相；
**强调只用一种手法** —— 需要你动手的那块（待你确认的申请）标题条深一档
+ 左侧一条短棕条 + 红点数字。别的区块一律不强调。

一条红线：**连接码区分大小写**，界面上任何地方都不许对它 upper/lower，
输入框也不许自动转大写。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ui import theme


def _field(label_text, widget, tag=''):
    """一行「标签 + 控件」。返回整行（要藏起来时藏这一行就行）。"""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lab = QLabel(label_text)
    lab.setObjectName('daySub')
    lab.setFixedWidth(56)
    lay.addWidget(lab)
    lay.addWidget(widget, 1)
    if tag:
        t = QLabel(tag)
        t.setObjectName('rowTag')
        lay.addWidget(t)
    return row


def _divider():
    """区块之间那条细线。不留白分隔，用线 —— 板子看起来才是一整块。"""
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f'background:{theme.CARD_BORDER};')
    return line


def _section(title, alert=False, hint=''):
    """一个区块 = 浅暖色标题条 + 白底内容。

    返回 (整块, 标题条布局, 内容布局)。`alert=True` 是**全页唯一的强调手法**，
    留给"需要你动手"的那块；别的地方请求它就是在削弱重点。
    """
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    head = QWidget()
    head.setObjectName('alertHead' if alert else 'sectionHead')
    # 普通 QWidget 要吃 QSS 背景必须开这个属性，否则背景根本画不出来
    head.setAttribute(Qt.WA_StyledBackground, True)
    hl = QHBoxLayout(head)
    hl.setContentsMargins(11 if alert else 14, 7, 14, 7)
    hl.setSpacing(8)
    if alert:
        bar = QFrame()
        bar.setFixedWidth(3)
        bar.setStyleSheet(f'background:{theme.ACCENT};')
        hl.addWidget(bar)          # 左侧短棕条：和待办页"逾期行首红竖条"同一手法
    title_lab = QLabel(title)
    title_lab.setObjectName('dayHeader')
    hl.addWidget(title_lab)
    hl.addStretch(1)
    if hint:
        hint_lab = QLabel(hint)
        hint_lab.setObjectName('daySub')
        hl.addWidget(hint_lab)
    outer.addWidget(head)

    body_w = QWidget()
    body = QVBoxLayout(body_w)
    body.setContentsMargins(14, 10, 14, 12)
    body.setSpacing(8)
    outer.addWidget(body_w)
    return box, hl, body


def _badge(count, mute=False):
    """数字徽章。红色只给"真的等你处理"，纯计数用中性灰。"""
    lab = QLabel(str(count))
    bg = theme.NEUTRAL_BG if mute else theme.RUN_RED
    fg = theme.NEUTRAL_TEXT if mute else theme.CARD
    lab.setStyleSheet(f'background:{bg}; color:{fg}; border-radius:8px;'
                      f'padding:0 6px; font-size:11px; font-weight:bold;')
    return lab


class AccountTab(QWidget):
    """账号页。对外只有信号和几个 set_xxx，不主动去问网络。"""

    sig_login_requested = Signal(str, str)          # (手机号, 密码)
    sig_signup_requested = Signal(str, str, str)    # (手机号, 密码, 昵称)
    sig_logout_requested = Signal()
    sig_pair_requested = Signal(str, str)           # (对方连接码, 留言)
    sig_pair_approve = Signal(str)                  # (pair_id)
    sig_pair_reject = Signal(str)                   # (pair_id)
    sig_pair_remove = Signal(str)                   # (pair_id)
    sig_open_chat = Signal(str)                     # (pair_id)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('accountTab')
        self._logged_in = False
        self._register_mode = False
        self._info = {}          # 登录回执：uid / code / phone / nickname
        self._peers = []
        self._badges = {}        # 标题条数字徽章：{标题条布局的 id: QLabel}
        self._build()

    # ---------- 构造 ----------

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName('taskScroll')        # 复用既有的滚动条样式
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)

        holder = QWidget()
        holder.setObjectName('taskScrollContent')
        board = QVBoxLayout(holder)
        board.setContentsMargins(0, 0, 0, 0)
        board.setSpacing(0)

        self._login_box = self._build_login()
        self._logged_box = self._build_logged()
        board.addWidget(self._login_box)
        board.addWidget(self._logged_box)
        board.addStretch(1)

        self._scroll.setWidget(holder)
        outer.addWidget(self._scroll)
        self._apply_state()
        self.set_connected(False)       # 一开始还没连上：按钮先灰着，说清楚原因

    def _build_login(self):
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        box, head, body = _section('登录 / 注册')
        self.login_hint = QLabel('登录后就能看到自己的连接码')
        self.login_hint.setObjectName('daySub')
        head.addWidget(self.login_hint)

        self.phone_edit = QLineEdit()
        self.phone_edit.setObjectName('taskInput')
        self.phone_edit.setPlaceholderText('手机号')
        self.password_edit = QLineEdit()
        self.password_edit.setObjectName('taskInput')
        self.password_edit.setPlaceholderText('密码')
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.nickname_edit = QLineEdit()
        self.nickname_edit.setObjectName('taskInput')
        self.nickname_edit.setPlaceholderText('别人看到的名字，可以留空')
        self.email_edit = QLineEdit()
        self.email_edit.setObjectName('taskInput')
        self.email_edit.setPlaceholderText('以后用来找回密码')
        self.email_edit.setEnabled(False)
        self.location_edit = QLineEdit()
        self.location_edit.setObjectName('taskInput')
        self.location_edit.setPlaceholderText('以后用来看天气')
        self.location_edit.setEnabled(False)

        body.addWidget(_field('手机号', self.phone_edit))
        body.addWidget(_field('密码', self.password_edit))
        self.nickname_row = _field('昵称', self.nickname_edit)
        self.email_row = _field('邮箱', self.email_edit, tag='以后再做')
        self.location_row = _field('所在地', self.location_edit, tag='以后再做')
        body.addWidget(self.nickname_row)
        body.addWidget(self.email_row)
        body.addWidget(self.location_row)

        btns = QWidget()
        bl = QHBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        self.login_btn = QPushButton('登录')
        self.login_btn.setObjectName('addBtn')          # 主按钮：实心棕
        self.switch_btn = QPushButton('注册新账号')
        self.login_btn.clicked.connect(self._on_main_button)
        self.switch_btn.clicked.connect(self._toggle_register)
        bl.addWidget(self.login_btn)
        bl.addWidget(self.switch_btn)
        bl.addStretch(1)
        body.addWidget(btns)

        # 错误单独占一行、红色 —— 别再只往标题栏那行灰字里塞：
        # 登录失败时用户只看得到"点了没反应"，根本注意不到角落的小字
        self.error_label = QLabel('')
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f'color:{theme.RUN_RED}; font-size:12px;')
        self.error_label.setVisible(False)
        body.addWidget(self.error_label)

        lay.addWidget(box)
        return wrap

    def _build_logged(self):
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ① 我的账号
        box_a, head_a, body_a = _section('我的账号')
        self.phone_label = QLabel('—')
        self.nickname_label = QLabel('—')
        body_a.addWidget(_field('手机号', self.phone_label))
        body_a.addWidget(_field('昵称', self.nickname_label))
        self.email_label = QLabel('—（以后再做）')
        self.email_label.setObjectName('daySub')
        self.location_label = QLabel('—（以后再做）')
        self.location_label.setObjectName('daySub')
        body_a.addWidget(_field('邮箱', self.email_label))
        body_a.addWidget(_field('所在地', self.location_label))
        acts = QWidget()
        al = QHBoxLayout(acts)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        self.logout_btn = QPushButton('退出登录')
        self.logout_btn.clicked.connect(self.sig_logout_requested.emit)
        al.addWidget(self.logout_btn)
        al.addStretch(1)
        body_a.addWidget(acts)
        lay.addWidget(box_a)
        lay.addWidget(_divider())

        # ② 我的连接码
        box_b, _, body_b = _section('我的连接码')
        code_row = QWidget()
        cr = QHBoxLayout(code_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(10)
        self.code_box = QWidget()
        self.code_box.setObjectName('innerRow')         # 「一行东西」：极浅暖 + 描边
        self.code_box.setAttribute(Qt.WA_StyledBackground, True)
        cbl = QHBoxLayout(self.code_box)
        cbl.setContentsMargins(12, 10, 12, 10)
        self.code_label = QLabel('—')
        self.code_label.setStyleSheet(
            f'color:{theme.ACCENT_DARK}; font-size:20px; font-weight:bold;'
            f'letter-spacing:2px;')                     # 靠字号与字色跳出来，不靠底色
        self.copy_btn = QPushButton('复制')
        self.copy_btn.clicked.connect(self._copy_code)
        cbl.addWidget(self.code_label, 1)
        cbl.addWidget(self.copy_btn)
        cr.addWidget(self.code_box, 1)
        body_b.addWidget(code_row)
        tip = QLabel('把这串码发给朋友；对方申请之后，下面会出现「待你确认的申请」。')
        tip.setObjectName('daySub')
        tip.setWordWrap(True)
        body_b.addWidget(tip)
        lay.addWidget(box_b)
        lay.addWidget(_divider())

        # ③ 连接别人
        box_c, _, body_c = _section('连接别人')
        self.peer_code_edit = QLineEdit()
        self.peer_code_edit.setObjectName('taskInput')
        self.peer_code_edit.setPlaceholderText('对方的连接码（区分大小写）')
        self.peer_msg_edit = QLineEdit()
        self.peer_msg_edit.setObjectName('taskInput')
        self.peer_msg_edit.setPlaceholderText('我是……（对方靠这句话认出你）')
        body_c.addWidget(_field('连接码', self.peer_code_edit))
        body_c.addWidget(_field('留言', self.peer_msg_edit))
        apply_row = QWidget()
        apl = QHBoxLayout(apply_row)
        apl.setContentsMargins(0, 0, 0, 0)
        self.apply_btn = QPushButton('申请连接')
        self.apply_btn.setObjectName('addBtn')
        self.apply_btn.clicked.connect(self._on_apply)
        apl.addWidget(self.apply_btn)
        apl.addStretch(1)
        body_c.addWidget(apply_row)
        self.outgoing_list = QVBoxLayout()
        self.outgoing_list.setContentsMargins(0, 0, 0, 0)
        self.outgoing_list.setSpacing(6)
        body_c.addLayout(self.outgoing_list)
        lay.addWidget(box_c)
        lay.addWidget(_divider())

        # ④ 待你确认的申请 —— 全页唯一的强调
        box_d, self.requests_head, body_d = _section('待你确认的申请', alert=True)
        self.request_list = QVBoxLayout()
        self.request_list.setContentsMargins(0, 0, 0, 0)
        self.request_list.setSpacing(6)
        body_d.addLayout(self.request_list)
        lay.addWidget(box_d)
        lay.addWidget(_divider())

        # ⑤ 已连接
        box_e, self.contacts_head, body_e = _section('已连接')
        self.contact_list = QVBoxLayout()
        self.contact_list.setContentsMargins(0, 0, 0, 0)
        self.contact_list.setSpacing(6)
        body_e.addLayout(self.contact_list)
        lay.addWidget(box_e)
        return wrap

    # ---------- 与外部（PetWindow）的接口 ----------

    def set_logged_in(self, info):
        """info 为 None 表示退出登录；否则是登录回执（uid / code / phone / nickname）"""
        self._info = dict(info or {})
        self._logged_in = bool(info)
        if self._logged_in:
            self.error_label.setVisible(False)      # 登进去了，上一轮的报错就不留着了
            self.phone_label.setText(self._info.get('phone') or '—')
            self.nickname_label.setText(self._info.get('nickname') or '（没填）')
            self.code_label.setText(self._info.get('code') or '—')
            self._register_mode = False
        self._apply_state()

    def set_peers(self, peers):
        """整版刷新会话列表。收到就重画这几块 —— 列表不长，增量刷新不值得。"""
        self._peers = list(peers or [])
        self._render_outgoing()
        self._render_requests()
        self._render_contacts()

    def set_error(self, code, message):
        """服务器回来的错。**只按 code 分支**，中文文案随时会改。

        额外照顾一种最常见的情况：连上的其实是**旧版服务器**。它不认账号协议，
        回的是一句「未知消息类型: login」且**没有 code** —— 那时把原文摆给用户没用，
        得直接告诉他"服务器要升级"。
        """
        text = message or code or '出错了'
        if not code and '未知消息类型' in text:
            text = ('连上的服务器还是旧版，不认账号协议（它回了：' + text + '）。'
                    '请把服务器更新到新版，或者把 config.json 的 ws_url 指向新的服务器。')
        self.error_label.setText(text)
        self.error_label.setVisible(True)

    def set_connected(self, connected):
        """网络状态变了。

        不只是让"申请连接"灰掉：**登录/注册按钮也得跟着灰** —— 否则用户在网络
        还没建立时点一下，那个包会被客户端丢掉（只在 stderr 留一行），
        而界面上一切照旧，看起来就是"按钮坏了"。宁可灰着并说明原因。
        """
        connected = bool(connected)
        self.apply_btn.setEnabled(connected)
        self.login_btn.setEnabled(connected)
        if not connected and not self._logged_in:
            self.login_hint.setText('正在连服务器…')
        elif not connected:
            self.login_hint.setText('连接断了，正在重连…')

    # ---------- 状态切换 ----------

    def _apply_state(self):
        self._login_box.setVisible(not self._logged_in)
        self._logged_box.setVisible(self._logged_in)
        self.nickname_row.setVisible(self._register_mode)
        self.email_row.setVisible(self._register_mode)
        self.location_row.setVisible(self._register_mode)
        self.login_btn.setText('创建账号' if self._register_mode else '登录')
        self.switch_btn.setText('返回登录' if self._register_mode else '注册新账号')

    def _toggle_register(self):
        self._register_mode = not self._register_mode
        self.login_hint.setText('注册新账号' if self._register_mode
                                else '登录后就能看到自己的连接码')
        self._apply_state()

    # ---------- 按钮 ----------

    def _on_main_button(self):
        phone = self.phone_edit.text().strip()
        password = self.password_edit.text()
        if self._register_mode:
            self.sig_signup_requested.emit(phone, password,
                                           self.nickname_edit.text().strip())
        else:
            self.sig_login_requested.emit(phone, password)

    def _on_apply(self):
        # 连接码**原样发**：它区分大小写，这里连 strip 之外什么都不做
        code = self.peer_code_edit.text().strip()
        if not code:
            self.login_hint.setText('先填对方的连接码')
            return
        self.sig_pair_requested.emit(code, self.peer_msg_edit.text().strip())
        self.peer_code_edit.clear()
        self.peer_msg_edit.clear()

    def _copy_code(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.code_label.text())
        self.login_hint.setText('连接码已复制')

    # ---------- 列表渲染 ----------

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _empty(self, layout, text):
        lab = QLabel(text)
        lab.setObjectName('daySub')
        lab.setWordWrap(True)
        layout.addWidget(lab)

    @staticmethod
    def _peer_name(peer):
        return peer.get('peer_nickname') or peer.get('peer_phone') or '对方'

    def _render_outgoing(self):
        self._clear(self.outgoing_list)
        mine = [p for p in self._peers if p.get('requested_by') == self._info.get('uid')]
        for p in mine:
            if p.get('status') == 'pending':
                self._empty(self.outgoing_list,
                            f"已申请连接 {self._peer_name(p)}，等对方同意")
            elif p.get('status') == 'rejected':
                self._empty(self.outgoing_list,
                            f"{self._peer_name(p)} 拒绝了这次申请")

    def _render_requests(self):
        self._clear(self.request_list)
        # 别人发给我、还没处理的 —— 这才是"需要你动手"
        pending = [p for p in self._peers
                   if p.get('status') == 'pending'
                   and p.get('requested_by') != self._info.get('uid')]
        if not pending:
            self._empty(self.request_list, '暂时没有新的申请。')
            self._set_badge(self.requests_head, 0)
            return
        self._set_badge(self.requests_head, len(pending))
        for p in pending:
            row = QWidget()
            row.setObjectName('innerRow')
            row.setAttribute(Qt.WA_StyledBackground, True)
            rl = QVBoxLayout(row)
            rl.setContentsMargins(12, 10, 12, 10)
            rl.setSpacing(4)
            who = QLabel(f"{p.get('peer_phone') or '（没有手机号）'}"
                         f"{('  ' + p['peer_nickname']) if p.get('peer_nickname') else ''}")
            who.setObjectName('dayHeader')
            rl.addWidget(who)
            msg = QLabel('留言：' + (p.get('message') or '（没有留言）'))
            msg.setObjectName('daySub')
            msg.setWordWrap(True)
            rl.addWidget(msg)
            acts = QWidget()
            al = QHBoxLayout(acts)
            al.setContentsMargins(0, 0, 0, 0)
            al.setSpacing(8)
            ok = QPushButton('同意')
            ok.setObjectName('addBtn')
            no = QPushButton('拒绝')
            pid = p.get('pair_id')
            ok.clicked.connect(lambda _=False, x=pid: self.sig_pair_approve.emit(x))
            no.clicked.connect(lambda _=False, x=pid: self.sig_pair_reject.emit(x))
            al.addWidget(ok)
            al.addWidget(no)
            al.addStretch(1)
            rl.addWidget(acts)
            self.request_list.addWidget(row)

    def _render_contacts(self):
        self._clear(self.contact_list)
        accepted = [p for p in self._peers if p.get('status') == 'accepted']
        self._set_badge(self.contacts_head, len(accepted), mute=True)
        if not accepted:
            self._empty(self.contact_list,
                        '还没有连接任何人。把上面的连接码发给朋友，或者填别人的码申请。')
            return
        for p in accepted:
            row = QWidget()
            row.setObjectName('innerRow')
            row.setAttribute(Qt.WA_StyledBackground, True)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 9, 12, 9)
            rl.setSpacing(8)
            name = QLabel(f"{self._peer_name(p)}  {p.get('peer_phone') or ''}")
            name.setObjectName('dayHeader')
            rl.addWidget(name)
            rl.addStretch(1)
            chat = QPushButton('聊天')
            rm = QPushButton('解除')
            pid = p.get('pair_id')
            chat.clicked.connect(lambda _=False, x=pid: self.sig_open_chat.emit(x))
            rm.clicked.connect(lambda _=False, x=pid: self.sig_pair_remove.emit(x))
            rl.addWidget(chat)
            rl.addWidget(rm)
            self.contact_list.addWidget(row)

    def _set_badge(self, head_layout, count, mute=False):
        """标题条右侧的数字徽章。count=0 就拿掉，免得挂个 0 在标题上。"""
        old = self._badges.get(id(head_layout))
        if old is not None:
            # 先 setParent(None) 把它从布局里摘掉再 deleteLater：
            # deleteLater 是延迟销毁，不摘的话旧徽章会继续显示到下一轮事件循环，
            # 界面上就会出现"数字已经清了、红点还挂着"的一帧
            old.setParent(None)
            old.deleteLater()
            self._badges.pop(id(head_layout), None)
        if count:
            lab = _badge(count, mute=mute)
            head_layout.insertWidget(head_layout.count() - 1, lab)
            self._badges[id(head_layout)] = lab
