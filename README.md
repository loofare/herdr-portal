# herdr-portal

![HERDR Portal · 基于真实脱敏界面的 README 封面](assets/banner.png)

**HERDR 全局看板** — 把当前 Herdr 会话里的全部 workspace / tab / pane 聚合成一块实时看板。一个插件，两种形态：

- **TUI 看板**（`prefix+a`）：Mission Control 风格，Agent 三列 + 窗口独立视图，回车直达会话
- **网页大屏**（`prefix+shift+a`）：指挥 / 霓虹 / 浅色 / 深色四主题，结构化进展，点卡片定位 Herdr 并弹终端到前台、网页端直接回复 Agent、最近输出 Markdown 渲染

![herdr 0.7+](https://img.shields.io/badge/herdr-0.7%2B-8a2be2) ![platforms](https://img.shields.io/badge/platforms-macOS%20%E2%80%A2%20Linux-informational) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.9%2B-orange)

## 预览

**网页看板**（默认指挥主题）：复刻 Mission Control 参考图的左侧命令栏、系统状态顶栏、红/蓝/绿状态列与终端状态条；待确认列为空时仍会自动隐藏。

![web board](assets/web-board.png)

**网页端回复**：点卡片定位 Herdr，点卡片右上角 ↩ 展开回复区——输入框 + 该 Agent 最近输出（Markdown 渲染、实时跟随）。

![web reply](assets/web-reply.png)

**窗口视图**：SSH / Shell 普通终端在独立视图里，不占用主看板。

![web windows](assets/web-windows.png)

**TUI 看板**（真实 TUI 渲染 · 脱敏演示数据）：图中待确认为空，因此自动收起为「执行中 / 已就绪」两列；保留真实选中态、详情栏与快捷键提示。

![tui board](assets/tui-board.png)

## 功能特性

- **聚合所有 Agent 状态**：待确认 / 执行中 / 空闲 / 已完成，以及普通窗口
- **Agent 类型识别**：PI、OMP、Claude、Codex 等 20+ 种
- **结构化实时进展**：当前阶段（执行命令 / 修改代码 / 等待子任务 / 等待确认…）+ 执行标题 + 工具类型 + 最近活动时间
- **动态待确认列**：平时零占用，有 Agent 停下等你（授权/提问）时自动弹出并在顶部统计中闪烁提醒
- **点击直达**：网页/TUI 点卡片 → Herdr 切到对应工作区/Tab/Pane，并把承载 Herdr 的终端窗口带到前台（自动识别 Ghostty / iTerm2 / Terminal / kitty / Alacritty / WezTerm 等）
- **网页端回复 Agent**：文字直发到该 Agent 终端（空闲走 `agent prompt`，执行中模拟键盘输入），支持粘贴多行
- **稳定可靠**：网页服务独立于 Herdr 运行（关 popup 不断线）、断线保留数据自动重连、滚动位置保持、数据指纹跳过无效重渲染

## 快速开始

```bash
herdr plugin install loofare/herdr-portal
```

然后绑定快捷键（`~/.config/herdr/config.toml`）：

```toml
[[keys.command]]
key = "prefix+a"
type = "plugin_action"
command = "herdr-portal.open-board"
description = "open global board TUI"

[[keys.command]]
key = "prefix+shift+a"
type = "plugin_action"
command = "herdr-portal.open-web"
description = "open web portal"
```

最后 `herdr server reload-config`，即可使用。

## TUI 交互指南

打开后默认是 **Agent 看板**（三列）：

- **动态列**：待确认为空时只有「执行中 / 已就绪」两列；有 Agent 停下等你时，待确认列自动弹出并排第一
- **虚拟滚动条**：某列卡片超出可视区域时，列右侧出现彩色滚动条，滑块比例和位置实时跟随
- **结构化卡片**：徽标/工作区 → 标题 → `▸ 阶段 · 执行标题` → 状态/工具/Pane ID
- **选中详情栏**（终端足够高时出现）：当前阶段、执行标题、位置路径、最近输出摘要
- **回车直达**：`Enter` 跳转到该 Pane 并**立即关闭面板**，直接露出定位好的会话；跳转失败则保持面板并提示原因
- **窗口视图**：`Tab` 或 `v` 切换到窗口（SSH/Shell）网格，再按一次切回

## 快捷键速查

### TUI

| 键 | 作用 |
| --- | --- |
| `↑ ↓ ← →` / `hjkl` | 选择卡片 / 切换列 |
| `Enter` | 跳转到该 Pane 并关闭面板 |
| `Tab` / `v` | Agent 看板 ↔ 窗口视图 |
| `1-3` | 直选列 |
| `r` | 立即刷新 |
| `q` / `Esc` | 退出面板 |

### 网页端

| 操作 | 效果 |
| --- | --- |
| 点击卡片 | 定位 Herdr 到该 Pane，并把终端窗口带到前台 |
| 点击卡片右上角 `↩` | 展开回复区（输入框 + 最近输出） |
| `Enter` / `Shift+Enter` / `Esc` | 发送 / 换行 / 收起回复区 |
| 左侧底部「浅色 / 深色 / 霓虹 / 指挥」 | 四种主题切换（默认指挥，记忆选择） |
| 「状态看板 / 工作区 / 窗口」 | 三种视图切换 |

## 使用场景

- **多项目并行监控**：几个 Agent 同时跑在不同 workspace，看板一眼看清谁在执行、谁在等你，点一下直达现场
- **远程确认与回复**：Agent 卡在授权/提问时，待确认列自动弹出，在网页端输入框直接回复，不用切回终端
- **大屏/投屏监督**：网页版放在副屏或平板，实时滚动最新进展，工作区视图按项目分组查看
- **窗口总览**：SSH 服务器、日志跟踪等普通终端集中在窗口视图，不与 Agent 状态混排

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `HERDR_PORTAL_PORT` | 网页端口（默认 8787） |
| `HERDR_PORTAL_NO_FRONT=1` | 点击卡片时不让终端窗口弹到前台 |

服务管理：`python3 board/daemon.py start|stop|restart|status`（网页服务由插件自动拉起，日志在 `~/.local/state/herdr-portal/server.log`）。

## 本地开发

```bash
herdr plugin link /path/to/herdr-portal
herdr server reload-config
```

结构：

```
board/
  tui.py          # curses TUI 看板
  collect.py      # 采集 herdr snapshot + 会话解析
  server.py       # 本地网页服务
  daemon.py       # 服务进程管理（脱离 Herdr popup 运行）
  web/            # 网页前端（原生 JS，零依赖）
scripts/
  open-board.sh   # 打开 TUI（plugin pane overlay）
  open-web.sh     # 启动网页服务并打开/复用浏览器标签
```

## 要求

- herdr 0.7+
- Python 3.9+（macOS 自带，Linux 需安装）
- 网页大屏需要浏览器（Chrome / Safari / Edge 均可）

## License

[MIT](LICENSE)
