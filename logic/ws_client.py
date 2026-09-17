"""WebSocket 通信客户端 —— QWebSocket 信号驱动，无需子线程

连接流程：
  connect_to_server() → connected 信号 → 自动发送 register 注册身份
断线处理：
  disconnected / errorOccurred 信号 → 5 秒后自动重连（服务器随时可启动）
消息协议见 YierBubu/docs/WebSocket开发文档.md 第 5 节。
"""
import json

from PySide6.QtCore import QObject, QUrl, Signal, QTimer
from PySide6.QtWebSockets import QWebSocket

from core import settings


class WsClient(QObject):
    """一二 ↔ 布布 通信客户端（所有回调都在主线程，可直接操作 UI）"""

    sig_message = Signal(str, str)      # (sender, content)
    sig_history = Signal(list)          # 历史消息列表 [{sender, receiver, content, timestamp}]
    sig_peer_online = Signal(str)       # 对方上线（identity）
    sig_peer_offline = Signal(str)      # 对方下线（identity）
    sig_status = Signal(str)            # 连接状态描述（调试/提示用）

    def __init__(self, url=None, identity=None, token=None):
        super().__init__()
        self.url = url or settings.WS_URL
        self.identity = identity or settings.IDENTITY
        # token 用 is not None 判断（不是 or），这样显式传 '' 能关掉鉴权而不回落到 settings
        self.token = token if token is not None else settings.WS_TOKEN

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

    def send_chat(self, to, content):
        """发送一条聊天消息"""
        if not self._connected:
            self.sig_status.emit('尚未连接服务器，消息未发送')
            return False
        msg = json.dumps({'type': 'chat', 'to': to, 'content': content}, ensure_ascii=False)
        self._socket.sendTextMessage(msg)
        return True

    def query_history(self, limit=20):
        """请求最近 limit 条聊天记录（结果以 history 消息经 sig_message 返回）"""
        if not self._connected:
            return
        self._socket.sendTextMessage(json.dumps({'type': 'query_history', 'limit': limit}))

    def close(self):
        """主动断开（退出桌宠时调用，不再重连）"""
        self._closing = True
        self._socket.close()

    # ---------- 连接生命周期 ----------

    def _on_connected(self):
        self._connected = True
        self.sig_status.emit('已连接服务器')
        # 连接成功第一件事：注册身份（协议要求，服务器据此转发消息）
        payload = {'type': 'register', 'identity': self.identity}
        if self.token:
            # 只在非空时带 token 字段 —— 服务器未启用鉴权时协议与今天逐字节一致
            payload['token'] = self.token
        self._socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))

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
        mtype = msg.get('type')
        if mtype == 'chat':
            self.sig_message.emit(msg.get('from', ''), msg.get('content', ''))
        elif mtype == 'online':
            self.sig_peer_online.emit(msg.get('identity', ''))
        elif mtype == 'offline':
            self.sig_peer_offline.emit(msg.get('identity', ''))
        elif mtype == 'history':
            self.sig_history.emit(msg.get('messages', []))
        elif mtype == 'error':
            self.sig_status.emit(f"服务器错误: {msg.get('message')}")
        # register_ok 无需处理：收到即视为注册成功
