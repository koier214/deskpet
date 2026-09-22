"""透明置顶桌宠窗口 —— 精灵显示 + 鼠标交互 + 右键菜单 + 线程管理"""
import sys
import time

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget, QLabel, QMenu, QApplication

from core import settings
from core.app_config import save_config
from core.pet_config import PetConfig
from logic.anim_worker import AnimationWorker
from logic.global_hotkey import GlobalHotkey
from logic.interact_worker import InteractionWorker
from logic.fixed_task_service import FixedTaskService
from logic.task_service import TaskService
from logic.usage_service import UsageService
from logic.ws_client import WsClient
from ui.chat_bubble import ChatBubble
from ui.chat_input_bubble import ChatInputBubble
from ui.chat_window import ChatWindow
from ui.history_window import HistoryWindow
from ui.menu_panel import MenuPanel
from ui.task_bubble import TaskBubble


class PetWindow(QWidget):
    """桌面宠物主窗口"""

    def __init__(self, pet_name='yier'):
        super().__init__()

        # ---- 加载角色配置 ----
        self.pet_conf = PetConfig.init_config(pet_name)
        settings.tunable_scale = self.pet_conf.scale

        # ---- 窗口属性 ----
        self._init_window()

        # ---- UI ----
        self._init_ui()

        # ---- 初始位置（屏幕右下角） ----
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.left() + screen.width() - self.width() - 50
        y = screen.top() + screen.height() - self.height() - 100
        self.move(x, y)

        # ---- 任务服务：数据与倒计时的唯一持有者 ----
        # 必须在任何待办视图之前建好，面板和气泡都只是它的视图
        self._task_service = TaskService(pet_name=self.pet_conf.petname)
        self._task_service.sig_finished.connect(self._on_task_finished)

        # ---- 固定任务：规则与「每天自动追加」的唯一持有者 ----
        # 追加时机只在这里接：启动补一次 + 跨零点补一次（睡醒后一次补齐）
        self._fixed_service = FixedTaskService(self._task_service,
                                               pet_name=self.pet_conf.petname)
        self._task_service.sig_day_changed.connect(self._on_day_changed)
        self._fixed_service.ensure_for()

        # ---- 使用时长服务：陪伴时长数据的唯一持有者 ----
        self._usage_service = UsageService(pet_name=self.pet_conf.petname)

        # ---- 一二菜单面板（懒加载） ----
        self._menu_panel = None

        # ---- 账号态：服务器回来的最新一版（账号页是懒加载的，先存在这儿） ----
        self._account_tab = None
        self._login_info = {}       # 登录回执：uid / code / phone / nickname
        self._peers = []            # 会话列表（谁申请我、我跟谁连上了）
        self._current_pair = None   # 当前在聊的那条会话

        # ---- 待办气泡（懒加载） ----
        self._task_bubble = None

        # ---- 聊天气泡（懒加载） ----
        self._chat_bubble = None
        self._task_bubble_suspended = False   # 待办气泡是否因聊天气泡临时隐藏

        # ---- 聊天输入气泡 + 全局热键 ----
        self._chat_input = None

        # ---- 常驻聊天窗口（懒加载） ----
        self._chat_window = None

        # ---- 聊天记录窗口（懒加载） ----
        self._history_window = None

        # ---- 工作线程 ----
        self._init_workers()

        # ---- 启动动画循环 ----
        self._start_animation()

        # ---- WebSocket 通信（QWebSocket 异步，无需子线程） ----
        self._init_ws()

        # ---- 聊天输入气泡 + Alt+Q 全局热键 ----
        self._init_chat_input()

    # ===================== 窗口设置 =====================
    def _init_window(self):
        """无边框、置顶、透明背景"""
        if sys.platform == 'win32':
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.SubWindow
                | Qt.NoDropShadowWindowHint
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
            )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    # ===================== UI =====================
    def _init_ui(self):
        """创建 QLabel 用于显示精灵帧"""
        self.label = QLabel(self)
        self.label.setScaledContents(True)
        self.label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)

        # 初始帧
        settings.current_img = self.pet_conf.default.images[0]
        settings.current_anchor = [0, 0]
        self._set_img()

        # 窗口尺寸 = 配置宽高
        self.setFixedSize(
            int(self.pet_conf.width),
            int(self.pet_conf.height),
        )

    def _set_img(self):
        """将 settings.current_img 显示到 QLabel 上 (GUI 线程)"""
        if settings.current_img is None:
            return

        w = settings.current_img.width()
        h = settings.current_img.height()
        self.label.setFixedSize(w, h)
        self.label.setPixmap(settings.current_img)

    def _move_window(self, dx, dy):
        """窗口位移 (AnimationWorker 方向位移用)"""
        self.move(self.pos().x() + dx, self.pos().y() + dy)

    # ===================== 线程管理 =====================
    def _init_workers(self):
        """创建 Animation 和 Interaction 两个 QThread + Worker"""
        # Animation
        self._anim_worker = AnimationWorker(self.pet_conf)
        self._anim_thread = QThread(self)
        self._anim_worker.moveToThread(self._anim_thread)

        # Interaction
        self._inter_worker = InteractionWorker(self.pet_conf)
        self._inter_thread = QThread(self)
        self._inter_worker.moveToThread(self._inter_thread)

    def _start_animation(self):
        """连接信号 → 启动线程"""
        # Animation signals → GUI
        self._anim_thread.started.connect(self._anim_worker.run)
        self._anim_worker.sig_setimg.connect(self._set_img)
        self._anim_worker.sig_move.connect(self._move_window)

        # Interaction signals → GUI
        self._inter_worker.sig_setimg.connect(self._set_img)
        self._inter_worker.sig_act_finished.connect(self._resume_animation)

        self._anim_thread.start()
        self._inter_thread.start()

    def _pause_animation(self):
        self._anim_worker.pause()

    def _resume_animation(self):
        """交互结束后恢复待机动画"""
        settings.current_img = self.pet_conf.default.images[0]
        settings.current_anchor = [0, 0]
        self._set_img()
        self._anim_worker.resume()

    # ===================== 鼠标事件 =====================
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._show_context_menu()
        elif event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_offset = event.globalPos() - self.pos()
            self._has_moved = False
            self._pause_animation()
            self._inter_worker.start_interact('mousedrag')
            event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self, '_is_dragging', False):
            new_pos = event.globalPos() - self._drag_offset
            if new_pos != self.pos():
                self.move(new_pos)
                self._has_moved = True
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            if not self._has_moved:
                # 点击（没拖动）→ 播放交互动画
                self._inter_worker.start_interact('patpat')
            else:
                # 拖动结束 → 停止交互，恢复待机
                self._inter_worker.stop_interact()

    # ===================== 右键菜单 =====================
    def _show_context_menu(self):
        menu = QMenu(self)
        task_action = menu.addAction('一二菜单')
        bubble_text = '关闭待办气泡' if self._task_bubble else '显示待办气泡'
        bubble_action = menu.addAction(bubble_text)
        chat_action = menu.addAction('聊天')
        history_action = menu.addAction('聊天记录')
        menu.addSeparator()
        exit_action = menu.addAction('退出 (Exit)')
        chosen = menu.exec_(QCursor.pos())
        if chosen == task_action:
            self._open_menu_panel()
        elif chosen == bubble_action:
            self._toggle_task_bubble()
        elif chosen == chat_action:
            self._toggle_chat_window()
        elif chosen == history_action:
            self._toggle_history_window()
        elif chosen == exit_action:
            self._quit()

    def _open_menu_panel(self, task_tab=False):
        """懒加载创建一二菜单，之后一律复用同一实例

        不能再用"不可见就重建"当条件：重建会把旧面板连同它持有的东西一起丢掉，
        用户拖过的窗口位置、日历选中日、输入框草稿全没了。
        """
        if self._menu_panel is None:
            self._menu_panel = MenuPanel(self._task_service, self._usage_service,
                                         self._fixed_service)
            # 账号页是懒加载的，造出来时会吱一声；接线（信号 ↔ 网络）就在那一刻做
            self._menu_panel.sig_account_tab_created.connect(self._wire_account_tab)
        if task_tab:
            self._menu_panel.show_task_tab()
        self._menu_panel.show()
        self._menu_panel.raise_()
        self._menu_panel.activateWindow()

    def _on_task_finished(self, task_id, task_text):
        """倒计时归零：头顶弹气泡提醒 + 把面板抢到前台

        service 不认识任何气泡控件，提醒这件 UX 只存在于 PetWindow。
        """
        self._show_chat_message(f'⏰ "{task_text}" 时间到！', 5000)
        self._open_menu_panel(task_tab=True)

    def _on_day_changed(self, new_today):
        """跨零点：先把当天该有的固定任务补上，再轮到视图重排

        本槽在创建 MenuPanel 之前就接上了，所以永远排在 TaskTab 的
        _on_day_changed 前面 —— 视图重排时看到的是补齐之后的数据。
        """
        self._fixed_service.ensure_for(new_today)

    # ===================== 待办气泡 =====================
    def _toggle_task_bubble(self):
        if self._task_bubble is not None:
            self._task_bubble.close()
            self._task_bubble = None
        else:
            self._task_bubble = TaskBubble(self._task_service)
            self._task_bubble.show()
            self._sync_bubble_position()

    def _sync_bubble_position(self):
        """把气泡放到一二左上方"""
        if self._task_bubble is None:
            return
        bw = self._task_bubble.width()
        bh = self._task_bubble.height()
        pw = self.width()
        x = self.pos().x() + (pw - bw) // 2  # 水平居中
        y = self.pos().y() - bh - 8           # 头顶上方 8px
        self._task_bubble.move(x, y)

    # ===================== WebSocket 通信 =====================
    def _init_ws(self):
        """创建 WS 客户端并接线（信号都在主线程，可直接操作 UI）"""
        self._ws = WsClient()
        self._ws.sig_message.connect(self._on_ws_message)
        self._ws.sig_history.connect(self._on_ws_history)
        self._ws.sig_login_ok.connect(self._on_ws_login_ok)
        self._ws.sig_peers.connect(self._on_ws_peers)
        self._ws.sig_pair_requested.connect(self._on_ws_pair_requested)
        self._ws.sig_error.connect(self._on_ws_error)
        self._ws.sig_peer_online.connect(self._on_ws_peer_online)
        self._ws.sig_peer_offline.connect(self._on_ws_peer_offline)
        # 连接状态只打 stderr：失败后每 5 秒重连一次，弹气泡会刷屏。
        # 但账号页要知道 —— 没连上时它的登录按钮得灰着，别让点击悄悄落空
        self._ws.sig_status.connect(self._on_ws_status)
        self._ws.connect_to_server()

    def _on_ws_status(self, text):
        print(f'[ws] {text}', file=sys.stderr)
        if self._account_tab is not None:
            self._account_tab.set_connected(getattr(self._ws, '_connected', False))

    # ---------- 账号 / 配对 ----------

    def _on_ws_login_ok(self, info):
        """登录成功：记住自己是谁，把连接码交给账号页，并弹一句告诉用户"""
        self._login_info = dict(info)
        self._peers = list(info.get('peers') or [])
        self._save_account_cfg()
        self._push_account()
        self._show_chat_message(f"已登录，我的连接码是 {info.get('code', '')}")

    def _on_ws_peers(self, peers):
        self._peers = list(peers or [])
        self._ensure_current_pair()
        self._save_account_cfg()
        self._push_account()

    def _ensure_current_pair(self):
        """确定"现在在跟谁聊"。

        只有一个已连接的人时**自动选他** —— 不这么做的话，用户从右键菜单打开聊天窗
        直接打字，会因为"没有当前会话"被挡在本地：消息根本没发出去，界面上只闪一个
        气泡，看起来就是"发送失败"（这个坑真踩过）。
        有多个人的时候不猜，保持 None，让用户到账号页点「聊天」明确选一个。
        会话被解除后，这里也会把过期的选择清掉。
        """
        if self._current_pair and self._find_pair(self._current_pair) is not None:
            return self._current_pair
        self._current_pair = None
        accepted = [p for p in self._peers if p.get('status') == 'accepted']
        if len(accepted) == 1:
            self._current_pair = accepted[0].get('pair_id')
        return self._current_pair

    def _save_account_cfg(self):
        """把账号态写回 config.json —— 下次开桌宠直接自动登录，不用再输密码。

        只写这五个键，文件里其它键（包括我们不认识的）一个都不动：那文件用户自己
        也会打开手改。**密码从来不落盘**，存下来的是服务器发的那张通行证。
        """
        try:
            save_config({
                'uid': self._login_info.get('uid', ''),
                'phone': self._login_info.get('phone', ''),
                'nickname': self._login_info.get('nickname', ''),
                'pass_token': self._ws.pass_token,
                'peers': self._peers,
            })
        except OSError as e:
            # 存不上不该把登录流程带崩：这次会话照常能用，只是下次要重新登录
            print(f'[config] 账号态存盘失败（下次需重新登录）: {e}', file=sys.stderr)

    def _on_ws_pair_requested(self, req):
        """有人申请连接你：头顶提醒一句，细节（手机号/留言/同意按钮）在账号页"""
        sender = req.get('from') or {}
        who = sender.get('nickname') or sender.get('phone') or '有人'
        self._show_chat_message(f'{who} 想连接你，去「账号」里点同意')
        self._push_account()

    def _on_ws_error(self, code, message):
        """服务器回的错：账号页按 code 显示，同时打 stderr 留痕"""
        if self._account_tab is not None:
            self._account_tab.set_error(code, message)
        print(f'[ws] 服务器返回错误 {code}: {message}', file=sys.stderr)

    def _on_ws_peer_online(self, uid):
        if self._current_pair and self._peer_uid(self._current_pair) == uid:
            self._show_chat_message(f'{self._peer_name(self._current_pair)} 上线了')

    def _on_ws_peer_offline(self, uid):
        if self._current_pair and self._peer_uid(self._current_pair) == uid:
            self._show_chat_message(f'{self._peer_name(self._current_pair)} 下线了')

    def _find_pair(self, pair_id):
        for p in self._peers:
            if p.get('pair_id') == pair_id:
                return p
        return None

    def _peer_uid(self, pair_id):
        p = self._find_pair(pair_id) or {}
        return p.get('peer_uid', '')

    def _peer_name(self, pair_id):
        p = self._find_pair(pair_id) or {}
        return p.get('peer_nickname') or p.get('peer_phone') or '对方'

    def _push_account(self):
        """把最新状态推给账号页。它是懒加载的，还没造出来就先什么都不做 ——
        等造出来那一刻再补推（见 _wire_account_tab）。"""
        if self._account_tab is None:
            return
        self._account_tab.set_logged_in(self._login_info or None)
        self._account_tab.set_peers(self._peers)
        self._account_tab.set_connected(getattr(self._ws, '_connected', False))

    def _wire_account_tab(self, tab):
        """账号页造出来了：接上它的信号，并把当前状态补推一版"""
        self._account_tab = tab
        tab.sig_login_requested.connect(self._ws.login)
        tab.sig_signup_requested.connect(self._ws.signup)
        tab.sig_logout_requested.connect(self._on_logout)
        tab.sig_pair_requested.connect(self._ws.pair_request)
        tab.sig_pair_approve.connect(self._ws.pair_approve)
        tab.sig_pair_reject.connect(self._ws.pair_reject)
        tab.sig_pair_remove.connect(self._ws.pair_remove)
        tab.sig_open_chat.connect(self._on_open_pair_chat)
        self._push_account()

    def _on_logout(self):
        self._ws.logout()
        self._ws.pass_token = ''    # 本机也别再拿这张票去连了
        self._login_info = {}
        self._peers = []
        self._current_pair = None
        self._save_account_cfg()     # 把 config.json 里的通行证一并清掉
        self._push_account()

    def _on_open_pair_chat(self, pair_id):
        """点已连接里的「聊天」：把这条设成当前会话，打开聊天窗并拉历史"""
        self._current_pair = pair_id
        if self._chat_window is None:
            self._ensure_chat_window()
        if self._chat_window is not None:
            self._chat_window.clear()
            self._suspend_task_bubble()
            self._sync_chat_window_position()
            self._chat_window.show()
            self._chat_window.raise_()
            self._chat_window.activateWindow()
            self._chat_window.focus_edit()
        self._ws.query_history(pair_id, 50)

    # ---------- 消息 ----------

    def _on_ws_message(self, pair_id, sender, content, msg_id, timestamp):
        """收到聊天消息 → 头顶弹气泡；聊天窗/记录窗开着**且是当前会话**才追加"""
        self._show_chat_bubble(pair_id, sender, content)
        if pair_id != self._current_pair:
            return          # 别的会话的消息：气泡提醒到了就够了，别串进当前窗口
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.append_message(sender, content, timestamp)
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.append_message(sender, content, timestamp)

    def _on_ws_history(self, pair_id, messages):
        """历史查询结果 → 聊天窗（气泡）/ 记录窗（文本）各自显示"""
        if pair_id != self._current_pair:
            return
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.clear()
            self._chat_window.append_history(messages)
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.clear()
            self._history_window.append_history(messages)

    def _show_chat_message(self, text, duration_ms=3000):
        """头顶弹聊天气泡；显示期间临时隐藏待办气泡（互斥）"""
        self._ensure_chat_bubble()
        self._suspend_task_bubble()
        self._sync_chat_bubble_position()
        self._chat_bubble.show_message(text, duration_ms)

    def _show_chat_bubble(self, pair_id, sender, content, duration_ms=3000):
        """聊天消息气泡：白色=我说的，棕色=对方说的，标题写对方的名字。

        "是不是我说的"只有这一层知道（uid 在手），气泡自己猜不出来 —— 所以由这里告诉它。
        """
        mine = bool(self._login_info.get('uid')) and sender == self._login_info.get('uid')
        self._ensure_chat_bubble()
        self._suspend_task_bubble()
        self._sync_chat_bubble_position()
        self._chat_bubble.show_chat(content, mine=mine,
                                    who='' if mine else self._peer_name(pair_id),
                                    duration_ms=duration_ms)

    def _ensure_chat_bubble(self):
        """懒创建头顶气泡；卡片增删导致高度变化时重新锚定位置"""
        if self._chat_bubble is None:
            self._chat_bubble = ChatBubble()
            self._chat_bubble.sig_hidden.connect(self._on_chat_bubble_hidden)
            self._chat_bubble.sig_changed.connect(self._sync_chat_bubble_position)

    def _on_chat_bubble_hidden(self):
        """聊天气泡消失 → 若无其他气泡占用头顶，恢复待办气泡"""
        self._restore_task_bubble_if_clear()

    def _suspend_task_bubble(self):
        """待办气泡与聊天/输入气泡互斥：隐藏它并记住"""
        if self._task_bubble is not None and self._task_bubble.isVisible():
            self._task_bubble.hide()
            self._task_bubble_suspended = True

    def _restore_task_bubble_if_clear(self):
        """聊天气泡、输入气泡、聊天窗都不显示时，恢复被暂停的待办气泡"""
        if not self._task_bubble_suspended or self._task_bubble is None:
            return
        if self._chat_bubble is not None and self._chat_bubble.isVisible():
            return
        if self._chat_input is not None and self._chat_input.isVisible():
            return
        if self._chat_window is not None and self._chat_window.isVisible():
            return
        self._task_bubble.show()
        self._sync_bubble_position()
        self._task_bubble_suspended = False

    def _sync_chat_bubble_position(self):
        """把聊天气泡放到一二头顶（输入气泡/聊天窗打开时叠在它们上方）"""
        if self._chat_bubble is None:
            return
        bw = self._chat_bubble.width()
        x = self.pos().x() + (self.width() - bw) // 2  # 水平居中
        if self._chat_input is not None and self._chat_input.isVisible():
            y = self._chat_input.y() - self._chat_bubble.height() - 8
        elif self._chat_window is not None and self._chat_window.isVisible():
            y = self._chat_window.y() - self._chat_bubble.height() - 8
        else:
            y = self.pos().y() - self._chat_bubble.height() - 8
        self._chat_bubble.move(x, y)

    # ===================== 聊天输入气泡 =====================
    def _init_chat_input(self):
        """创建输入气泡 + 注册 Alt+Q 系统级全局热键"""
        self._chat_input = ChatInputBubble(peer=settings.PEER)
        self._chat_input.sig_send.connect(self._on_input_send)
        # Alt+Q：任何软件里按都能切换输入气泡；parent 传自己，
        # 注册失败降级成应用内快捷键时 QShortcut 要挂在窗口上
        self._hotkey = GlobalHotkey('q', parent=self)
        self._hotkey.triggered.connect(self._toggle_chat_input)

    def _on_input_send(self, text):
        """回车发送到**当前会话**；聊天窗/记录窗开着则把"我说的话"也追加进去"""
        pair_id = self._ensure_current_pair()
        if not pair_id:
            self._show_chat_message('还没选联系人：到「账号」→ 已连接 里点「聊天」')
            return
        self._ws.send_chat(pair_id, text)
        my_uid = self._login_info.get('uid', '')
        if self._chat_window is not None and self._chat_window.isVisible():
            # 用**登录回执里的 uid** 标"我"。不能读 settings.UID —— 那是启动时
            # 装载的配置项，登录拿到的新 uid 不会写回去，用它的话自己的消息会被
            # 当成对方发的（气泡左右、颜色全反）
            self._chat_window.append_message(my_uid, text, time.time())
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.append_message(my_uid, text, time.time())

    def _toggle_chat_input(self):
        """Alt+Q：开/关输入气泡，隐藏时草稿暂存；与常驻聊天窗互斥"""
        if self._chat_input.isVisible():
            self._chat_input.hide()
            self._restore_task_bubble_if_clear()
        else:
            # 聊天入口同一时刻只留一个：常驻聊天窗开着就先收起来
            if self._chat_window is not None and self._chat_window.isVisible():
                self._chat_window.hide()
            self._suspend_task_bubble()
            self._sync_chat_input_position()
            self._chat_input.show()
            self._chat_input.raise_()
            self._chat_input.activateWindow()
            self._chat_input.focus_edit()

    def _sync_chat_input_position(self):
        """输入气泡悬浮在一二头顶"""
        if self._chat_input is None:
            return
        bw = self._chat_input.width()
        x = self.pos().x() + (self.width() - bw) // 2
        y = self.pos().y() - self._chat_input.height() - 8
        self._chat_input.move(x, y)

    # ===================== 常驻聊天窗口 =====================
    def _toggle_chat_window(self):
        """右键"聊天"：开关常驻聊天窗，打开时重新拉历史；与 Alt+Q 输入气泡互斥"""
        self._ensure_current_pair()      # 只有一个人就直接选他，别让打字白打
        self._ensure_chat_window()
        if self._chat_window.isVisible():
            self._hide_chat_window()
        else:
            # 聊天入口同一时刻只留一个：输入气泡开着就先藏起来（草稿保留）
            if self._chat_input is not None and self._chat_input.isVisible():
                self._chat_input.hide()
            self._suspend_task_bubble()
            self._sync_chat_window_position()
            self._chat_window.show()
            self._chat_window.raise_()
            self._chat_window.activateWindow()
            self._chat_window.focus_edit()
            if self._current_pair:
                self._ws.query_history(self._current_pair, 50)

    def _ensure_chat_window(self):
        """懒加载聊天窗：第一次用到才建（AGENTS.md 的懒加载约定）"""
        if self._chat_window is not None:
            return self._chat_window
        # identity 传的是**账号编号**：窗口靠它分辨"哪条是我说的"。
        # 不直接读 settings.UID —— 那是个配置项，只有 apply_to_settings 能写它；
        # 这里用登录回执里的 uid，语义更直接。
        self._chat_window = ChatWindow(identity=self._login_info.get('uid', ''))
        # 聊天窗里回车发送，走和输入气泡同一条发送路径
        self._chat_window.sig_send.connect(self._on_input_send)
        self._chat_window.sig_close_requested.connect(self._hide_chat_window)
        return self._chat_window

    def _hide_chat_window(self):
        """隐藏聊天窗（× 或再点右键"聊天"），并试着恢复头顶待办气泡"""
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.hide()
        self._restore_task_bubble_if_clear()

    def _sync_chat_window_position(self):
        """聊天窗放在一二头顶，并随一二移动；用户拖过标题条则按记住的偏移跟随"""
        if self._chat_window is None:
            return
        bw = self._chat_window.width()
        x = self.pos().x() + (self.width() - bw) // 2
        y = self.pos().y() - self._chat_window.height() - 8
        self._chat_window.anchor_to(x, y)

    # ===================== 聊天记录窗口 =====================
    def _toggle_history_window(self):
        """右键"聊天记录"：开关历史记录窗，打开时重新拉历史"""
        if self._history_window is None:
            self._history_window = HistoryWindow(identity=settings.IDENTITY)
        if self._history_window.isVisible():
            self._history_window.hide()
        else:
            self._history_window.show()
            self._history_window.raise_()
            self._history_window.activateWindow()
            if self._current_pair:
                self._ws.query_history(self._current_pair, 50)

    def moveEvent(self, event):
        """窗口移动时各个悬浮窗跟随（拖动一二、待机动画位移都会走到这里）"""
        super().moveEvent(event)
        self._sync_bubble_position()
        # 输入气泡要先于聊天气泡：聊天气泡叠在输入气泡上方，读的是它的 y
        if self._chat_input is not None and self._chat_input.isVisible():
            self._sync_chat_input_position()
        if self._chat_bubble is not None and self._chat_bubble.isVisible():
            self._sync_chat_bubble_position()
        if self._chat_window is not None and self._chat_window.isVisible():
            self._sync_chat_window_position()

    # ===================== 退出清理 =====================
    def _quit(self):
        self._hotkey.unregister()

        # 尽早落盘：后面两个线程的 wait(3000) 万一卡住也不丢数据
        self._task_service.shutdown()
        self._fixed_service.shutdown()
        self._usage_service.shutdown()

        if self._chat_window is not None:
            self._chat_window.close()
            self._chat_window = None

        if self._history_window is not None:
            self._history_window.close()
            self._history_window = None

        if self._chat_input is not None:
            self._chat_input.close()
            self._chat_input = None

        if self._chat_bubble is not None:
            self._chat_bubble.close()
            self._chat_bubble = None

        if self._task_bubble is not None:
            self._task_bubble.close()
            self._task_bubble = None

        if self._menu_panel is not None:
            self._menu_panel.close()
            self._menu_panel = None

        self._ws.close()

        self._anim_worker.kill()
        self._anim_thread.quit()
        self._anim_thread.wait(3000)

        self._inter_worker.kill()
        self._inter_thread.quit()
        self._inter_thread.wait(3000)

        self.close()
        QApplication.quit()
