"""透明置顶桌宠窗口 —— 精灵显示 + 鼠标交互 + 右键菜单 + 线程管理"""
import sys
import time

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QWidget, QLabel, QMenu, QApplication

from core import settings
from core.pet_config import PetConfig
from logic.anim_worker import AnimationWorker
from logic.global_hotkey import GlobalHotkey
from logic.interact_worker import InteractionWorker
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

        # ---- 使用时长服务：陪伴时长数据的唯一持有者 ----
        self._usage_service = UsageService(pet_name=self.pet_conf.petname)

        # ---- 一二菜单面板（懒加载） ----
        self._menu_panel = None

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
            self._menu_panel = MenuPanel(self._task_service, self._usage_service)
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
        self._ws.sig_peer_online.connect(lambda who: self._show_chat_message(f'{who} 上线了'))
        self._ws.sig_peer_offline.connect(lambda who: self._show_chat_message(f'{who} 下线了'))
        # 连接状态只打 stderr：鉴权失败/断线时每 5 秒重连一次，弹气泡会刷屏
        self._ws.sig_status.connect(lambda s: print(f'[ws] {s}', file=sys.stderr))
        self._ws.connect_to_server()

    def _on_ws_message(self, sender, content):
        """收到聊天消息 → 头顶弹气泡；聊天窗/记录窗开着则实时追加"""
        self._show_chat_bubble(sender, content)
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.append_message(sender, content, time.time())
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.append_message(sender, content, time.time())

    def _on_ws_history(self, messages):
        """历史查询结果 → 聊天窗（气泡）/ 记录窗（文本）各自显示"""
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

    def _show_chat_bubble(self, sender, content, duration_ms=3000):
        """聊天消息气泡：棕色/白色和"来自xx的消息"标题由 ChatBubble 按发送方决定"""
        self._ensure_chat_bubble()
        self._suspend_task_bubble()
        self._sync_chat_bubble_position()
        self._chat_bubble.show_chat(sender, content, duration_ms)

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
        """回车发送给布布；聊天窗/记录窗开着则把"我说的话"也追加进去"""
        self._ws.send_chat(settings.PEER, text)
        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.append_message(settings.IDENTITY, text, time.time())
        if self._history_window is not None and self._history_window.isVisible():
            self._history_window.append_message(settings.IDENTITY, text, time.time())

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
        if self._chat_window is None:
            self._chat_window = ChatWindow(identity=settings.IDENTITY)
            # 聊天窗里回车发送，走和输入气泡同一条发送路径
            self._chat_window.sig_send.connect(self._on_input_send)
            self._chat_window.sig_close_requested.connect(self._hide_chat_window)
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
            self._ws.query_history(20)

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
            self._ws.query_history(20)

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
