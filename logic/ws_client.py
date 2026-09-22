"""WebSocket 通信客户端 —— QWebSocket 信号驱动，无需子线程

账号模式（2026-09-22 起，协议 v2）：
  连接 → 手上有通行证就直接出示它（register）；没有就什么都不发，
  等界面上登录（login / signup）——登录成功时服务器顺带回一张通行证。
  消息按会话（pair_id）收发；跟谁能聊，要对方同意之后才算数。
断线处理：
  disconnected / errorOccurred 信号 → 5 秒后自动重连（服务器随时可启动）
协议见 YierBubu/docs/2026-09-22-账号与连接-正式规格.md 第 7 节。

一条规矩：**客户端只按 error 的 code 分支，不许去匹配中文 message**
（文案随时会改，code 才是契约）。
"""
import json

from PySide6.QtCore import QObject, QUrl, Signal, QTimer
from PySide6.QtWebSockets import QWebSocket

from core import settings


class WsClient(QObject):
    """一二 ↔ 布布 通信客户端（所有回调都在主线程，可直接操作 UI）"""

    # 登录/注册成功。dict 带 uid / code / nickname / phone / peers（signup 还带 pass_token）
    sig_login_ok = Signal(dict)
    # 收到一条消息：(pair_id, 发送者 uid, 内容, 消息 id, 时间戳)
    # **必须带 pair_id**：多会话之后，"这条是谁跟谁说的"全靠它，界面按它分桶
    sig_message = Signal(str, str, str, int, float)
    sig_history = Signal(str, list)      # (pair_id, 消息列表)
    sig_peers = Signal(list)             # 会话列表（有人申请/同意/解除都会来一版）
    sig_pair_requested = Signal(dict)    # 有人申请你：带 from.phone / from.nickname / message
    sig_peer_online = Signal(str)        # 某人上线（uid）
    sig_peer_offline = Signal(str)       # 某人下线（uid）
    sig_error = Signal(str, str)         # (code, message)
    sig_status = Signal(str)             # 连接状态描述（调试/提示用）

    def __init__(self, url=None, pass_token=None):
        super().__init__()
        self.url = url or settings.WS_URL
        # pass_token 用 is not None 判断（不是 or），这样显式传 '' 表示"这次不带通行证"
        self.pass_token = pass_token if pass_token is not None else settings.PASS_TOKEN
        self.uid = ''                   # 登录成功后填上，用来分辨"哪条消息是我说的"

        self._closing = False           # 主动关闭标记（避免退出后还重连）
        self._reconnect_pending = False
        self._connected = False

        # QWebSocket：Qt 原生异步网络类，收发都通过信号回调，不阻塞主线程
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.textMessageReceived.connect(self._on_text)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.errorOccurred.connect(self._on_error)

    # ---------- 对外接口 ----------

    def connect_to_server(self):
        """连接服务器（异步发起，成功/失败都会走信号回调）"""
        self.sig_status.emit(f'正在连接 {self.url} ...')
        self._socket.open(QUrl(self.url))

    def _send(self, payload):
        """统一出口。没连上就只回一句状态、不发 —— 别让调用方以为发出去了。"""
        if not self._connected:
            self.sig_status.emit('尚未连接服务器，这条没发出去')
            return False
        self._socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
        return True

    def login(self, phone, password):
        """用手机号 + 密码换一张通行证（结果走 sig_login_ok）"""
        return self._send({'type': 'login', 'phone': phone, 'password': password})

    def signup(self, phone, password, nickname=''):
        """注册新账号（结果走 sig_login_ok，回执里多一张 pass_token）"""
        return self._send({'type': 'signup', 'phone': phone, 'password': password,
                           'nickname': nickname})

    def logout(self):
        return self._send({'type': 'logout', 'pass_token': self.pass_token})

    def change_password(self, old_password, new_password):
        return self._send({'type': 'change_password', 'old_password': old_password,
                           'new_password': new_password,
                           'pass_token': self.pass_token})

    def send_chat(self, pair_id, content):
        """往某条会话里发一条消息"""
        return self._send({'type': 'chat', 'pair_id': pair_id, 'content': content})

    def pair_request(self, code, message=''):
        """填对方的连接码申请连接。**code 原样发，绝不转大小写**（它区分大小写）。"""
        return self._send({'type': 'pair_request', 'code': code, 'message': message})

    def pair_approve(self, pair_id):
        return self._send({'type': 'pair_approve', 'pair_id': pair_id})

    def pair_reject(self, pair_id):
        return self._send({'type': 'pair_reject', 'pair_id': pair_id})

    def pair_remove(self, pair_id):
        return self._send({'type': 'pair_remove', 'pair_id': pair_id})

    def pair_list(self):
        """拉会话列表（结果走 sig_peers）"""
        return self._send({'type': 'pair_list'})

    def query_history(self, pair_id, limit=50, since_id=None):
        """查某条会话的历史；since_id 用于断线后补拉（只要比它新的）"""
        payload = {'type': 'query_history', 'pair_id': pair_id, 'limit': limit}
        if since_id is not None:
            payload['since_id'] = since_id
        return self._send(payload)

    def close(self):
        """主动断开（退出桌宠时调用，不再重连）"""
        self._closing = True
        self._socket.close()

    # ---------- 连接生命周期 ----------

    def _on_connected(self):
        self._connected = True
        self.sig_status.emit('已连接服务器')
        # 手上有通行证就直接出示；没有就不发 —— 等界面上登录，别自作主张建号
        if self.pass_token:
            self._socket.sendTextMessage(json.dumps(
                {'type': 'register', 'pass_token': self.pass_token}, ensure_ascii=False))
        else:
            self.sig_status.emit('未登录：请在「账号」里用手机号登录')

    def _on_disconnected(self):
        self._connected = False
        if self._closing:
            return
        self.sig_status.emit('连接断开，5 秒后自动重连...')
        self._schedule_reconnect()

    def _on_error(self, err):
        if self._closing:
            return
        self.sig_status.emit(f'连接失败（{err}），5 秒后自动重连...')
        self._schedule_reconnect()

    def _schedule_reconnect(self):
        """防重复：同一时刻只排一个重连定时器"""
        if self._reconnect_pending:
            return
        self._reconnect_pending = True
        QTimer.singleShot(5000, self._do_reconnect)

    def _do_reconnect(self):
        self._reconnect_pending = False
        self.connect_to_server()

    # ---------- 服务器消息分发 ----------

    def _on_text(self, raw):
        """解析服务器推送的 JSON，按 type 分发到对应信号"""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            # 帧是合法 JSON 但不是对象（[] / null / "x" / 3）：下面的 msg.get 会抛
            # AttributeError，把整个客户端的回调链打断。数据来自网络，先挡住
            return
        mtype = msg.get('type')
        if mtype in ('register_ok', 'login_ok', 'signup_ok'):
            if msg.get('uid'):
                self.uid = msg['uid']
            if msg.get('pass_token'):
                self.pass_token = msg['pass_token']
            self.sig_login_ok.emit(msg)
        elif mtype == 'chat':
            self.sig_message.emit(msg.get('pair_id', ''), msg.get('from', ''),
                                  msg.get('content', ''), int(msg.get('id') or 0),
                                  float(msg.get('timestamp') or 0))
        elif mtype == 'online':
            self.sig_peer_online.emit(msg.get('uid', ''))
        elif mtype == 'offline':
            self.sig_peer_offline.emit(msg.get('uid', ''))
        elif mtype == 'history':
            self.sig_history.emit(msg.get('pair_id', ''), msg.get('messages', []))
        elif mtype == 'pair_requested':
            self.sig_pair_requested.emit(msg)
            # 有人申请你：光提醒不够 —— 会话列表也要刷新，否则「待你确认的申请」
            # 那一块永远空着，用户根本点不到同意
            self.pair_list()
        elif mtype == 'pair_list':
            self.sig_peers.emit(msg.get('peers', []))
        elif mtype in ('pair_added', 'pair_rejected', 'pair_removed'):
            # 会话有变化就自己去拉一版最新的，界面只管听 sig_peers 一种信号
            self.pair_list()
            self.sig_status.emit('会话有变化，正在刷新')
        elif mtype == 'error':
            self.sig_error.emit(msg.get('code', ''), msg.get('message', ''))
            self.sig_status.emit(f"服务器错误: {msg.get('message')}")
