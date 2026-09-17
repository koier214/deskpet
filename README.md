# 一二桌宠（deskpet）

基于 PySide6 的极简桌面宠物「一二」：常驻桌面、头顶挂待办气泡，并可与另一台电脑上的「布布」通过 WebSocket 聊天。

## 运行

Windows 用户：**双击 `启动桌宠.bat`**，首次运行会自动安装依赖，之后直接启动（无 cmd 黑窗口）。

也可以在命令行手动跑：

```powershell
pip install -r requirements.txt
python main.py
```

要求：Python 3.10 以上（PySide6 新版要求），除 PySide6 外没有其它第三方依赖。

## 配置（可选）

默认零配置即可运行。要改服务器地址、身份或密钥时，把 `config.example.json` 复制成 `config.json` 再改：

| 键 | 说明 | 默认 |
|---|---|---|
| `pet_name` | 角色名，决定 `res/<名字>/` 与数据文件位置 | `yier` |
| `identity` | 本机身份 | `yier` |
| `peer` | 聊天对象，不填则按身份推导 | 推导 |
| `ws_url` | 服务器地址，支持 `ws://` 与 `wss://` | `ws://localhost:8765` |
| `token` | 服务器密钥，留空表示服务器未开鉴权 | `""` |

`config.json` 不会进版本库（含密钥），提交模板请改 `config.example.json`。

## 关于聊天

聊天需要另一台机器运行 WebSocket 服务器（转发消息 + 存历史）。没有服务器时，桌宠照常运行，只在后台反复尝试重连。

## 命令行参数

```powershell
python main.py --server ws://192.168.1.5:8765   # 换服务器
python main.py --identity bubu --pet-name bubu  # 以布布身份运行
python main.py --token 你的密钥                  # 服务器开了鉴权时
```
