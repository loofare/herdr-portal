# herdr-portal

[English](README.md) · **简体中文**

![HERDR Portal · 基于真实脱敏界面的封面](assets/banner.png)

**HERDR 全局看板** — 把当前 Herdr 会话里的全部 workspace / tab / pane 聚合成一块实时看板。一个插件，两种形态：

- **TUI 看板** — 按 **`Ctrl+B` 再按 `A`**：Mission Control 风格，Agent 三列 + 窗口独立视图，回车直达会话
- **网页大屏** — 按 **`Ctrl+B` 再按 `Shift+A`**：指挥 / 霓虹 / 浅色 / 深色四主题，结构化进展，点卡片定位 Herdr 并弹终端到前台、网页端直接回复 Agent、最近输出 Markdown 渲染

![herdr 0.7+](https://img.shields.io/badge/herdr-0.7%2B-8a2be2) ![platforms](https://img.shields.io/badge/platforms-macOS%20%E2%80%A2%20Linux-informational) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.9%2B-orange)

## 推荐用法：`Ctrl+B` `A`

TUI 以 Herdr popup pane 的形式浮起，所以整个来回只有两下按键，手不离键盘：

```
Ctrl+B  A        看板浮在当前 pane 之上
↑ ↓ ← →          选中那个正在等你的 Agent（也可以直接鼠标点）
Enter            跳到该 pane —— 看板在跳转的同时自己关掉
```

不用切窗口、不用找鼠标、不用回忆「那个 Agent 刚才在哪个 tab」。`Ctrl+B` 是 Herdr 的 prefix，`A` 是看板，`Shift+A` 是同一块看板的网页版。因为跳转的瞬间看板就关闭了，这是一个连贯动作，而不是一个还需要你退出的模式。

## 预览

**网页看板**（默认指挥主题）：复刻 Mission Control 参考图的左侧命令栏、系统状态顶栏、红/蓝/绿状态列与终端状态条；待确认列为空时仍会自动隐藏。

![web board](assets/web-board.png)

**网页端回复**：点卡片定位 Herdr，点卡片右上角 ↩ 展开回复区——输入框 + 该 Agent 最近输出（Markdown 渲染、实时跟随）。

![web reply](assets/web-reply.png)

**窗口视图**：SSH / Shell 普通终端在独立视图里，不占用主看板。

![web windows](assets/web-windows.png)

**TUI 看板**（真实 TUI 渲染 · 脱敏演示数据）：图中待确认为空，因此自动收起为「执行中 / 已就绪」两列；表头带当前版本、五个可点动作入口（新 Tab / 新 Pane / 重命名 / 释放闲置 / 有新版时的更新按钮），下方是真实选中态、详情栏与快捷键提示。

![tui board](assets/tui-board.png)

## 功能特性

- **聚合所有 Agent 状态**：待确认 / 执行中 / 空闲 / 已完成，以及普通窗口
- **Agent 类型识别**：PI、OMP、Claude、Codex 等 20+ 种
- **结构化实时进展**：当前阶段（执行命令 / 修改代码 / 等待子任务 / 等待确认…）+ 执行标题 + 工具类型 + 最近活动时间
- **动态待确认列**：平时零占用，有 Agent 停下等你（授权/提问）时自动弹出并在顶部统计中闪烁提醒
- **点击直达**：网页/TUI 点卡片 → Herdr 切到对应工作区/Tab/Pane，并把承载 Herdr 的终端窗口带到前台（自动识别 Ghostty / iTerm2 / Terminal / kitty / Alacritty / WezTerm 等）
- **TUI 键盘与鼠标双支持**：键盘操作完整保留，同时可以点选卡片、再点一次（或双击）跳转、点列头切列
- **网页端回复 Agent**：文字直发到该 Agent 终端（空闲走 `agent prompt`，执行中模拟键盘输入），支持粘贴多行
- **稳定可靠**：网页服务独立于 Herdr 运行（关 popup 不断线）、断线保留数据自动重连、滚动位置保持、数据指纹跳过无效重渲染

## 快速开始

```bash
herdr plugin install loofare/herdr-portal
```

然后绑定快捷键（`~/.config/herdr/config.toml`）：

```toml
[[keys.command]]
key = "prefix+a"            # 即 Ctrl+B 再按 A
type = "plugin_action"
command = "herdr-portal.open-board"
description = "open global board TUI"

[[keys.command]]
key = "prefix+shift+a"      # 即 Ctrl+B 再按 Shift+A
type = "plugin_action"
command = "herdr-portal.open-web"
description = "open web portal"
```

最后 `herdr server reload-config`，然后按 **`Ctrl+B` `A`**。

> `prefix` 是 Herdr 的前缀键，默认 `Ctrl+B`。改过前缀的话按自己的来，插件只关心 `+a` 这一半。

## TUI 交互指南

**`Ctrl+B` `A`** 打开后默认是 **Agent 看板**（三列）：

- **动态列**：待确认为空时只有「执行中 / 已就绪」两列；有 Agent 停下等你时，待确认列自动弹出并排第一
- **虚拟滚动条**：某列卡片超出可视区域时，列右侧出现彩色滚动条，滑块比例和位置实时跟随
- **结构化卡片**：标题（主角）→ `▸ 阶段 · 执行标题` → 状态/工具/Pane ID；驱动框架（omp / pi / …）弱化成卡片右上角边框上的小写角标，工作区跟在标题右侧
- **选中详情栏**（终端足够高时出现）：当前阶段、执行标题、位置路径、最近输出摘要
- **回车直达**：`Enter` 跳转到该 Pane 并**立即关闭面板**，直接露出定位好的会话；跳转失败则保持面板并提示原因
- **窗口视图**：`Tab` 或 `v` 切换到窗口（SSH/Shell）网格，再按一次切回
- **释放闲置**：`X`（或点右上角的 `⌫ 释放闲置` 按钮）打开回收面板，勾选后按两次 `Enter` 关闭这些 Pane，腾出系统资源
- **就地重命名**：`E` 打开重命名面板，`Tab` 在 Pane 标题 / Tab 名称 / Workspace 名称之间切换，改完 `Enter` 保存
- **新开工作位**：`N` 在选中卡片所属工作区新开一个标签页，`s` / `S` 在选中 Pane 的右侧 / 下方切一个新 Pane；两者都继承选中卡片的目录，建好直接跳过去并关掉看板

### 鼠标

TUI 以键盘为主，但不是只能用键盘：

| 操作 | 效果 |
| --- | --- |
| 点击卡片 | 选中（详情栏立即跟随） |
| 再点一次已选中的卡片，或双击任意卡片 | 跳转到该 Pane 并关闭看板 |
| 点击某列空白处 | 把该列设为当前列 |
| 点击右上角 `⌫ 释放闲置` | 打开回收面板（面板内每行、阈值档位、按钮均可点） |
| 点击重命名面板里的三个胶囊 | 切换要改的是 Pane / Tab / Workspace |
| 点击右上角 `＋ 新 Tab` / `⬓ 新 Pane` | 在选中卡片的工作区 / 旁边新开一个，跳过去并关闭看板 |
| 点击右上角 `⬆ 更新 vX.Y.Z`（仅有新版时出现） | 同 `U`：第一次提示，第二次开新标签页执行更新 |
| 其他 | 下方键盘快捷键照常生效 |

鼠标上报是静默降级的：终端或 ncurses 不支持时，所有按键仍然照常工作。滚轮**故意没有绑定**——macOS 自带 ncurses 5.7 把「滚轮下滚」和「鼠标移动」上报在同一个 bit 上，绑了会变成移动鼠标就滚看板。

### 释放闲置（回收空闲 Pane）

看板右上角常驻 `⌫ 释放闲置` 按钮，键盘按 `X` 同样打开——**不占用原有任何键位**，面板关掉后一切照旧。

面板列出「可以安全回收」的 Pane，并解释每一条为什么可回收：

- **永不回收**：正在执行 / 等你确认的 Agent、当前聚焦的 Pane、看板自身所在的 Pane，以及前台跑着真实进程（ssh、vim、日志跟踪…）的窗口。它们出现在底部「受保护」一行，附带原因。
- **候选**：前台只剩静止 shell 的窗口 Pane（`静止 Shell`），以及空闲 / 已完成的 Agent（`⚠` 标记，风险更高，**默认不勾选**）。
- **静默时长**：看板每秒采样一次终端内容版本号，记录每个 Pane「最后一次有变化」的时刻，因此「静默 2h」是真实观测值而非猜测（记录落在 `~/.cache/herdr-portal/activity.json`）。
- **预选阈值**：`T` 或点右上角的阈值胶囊，在 `不限 / 5m / 30m / 2h` 之间切换，只影响默认勾选哪些，列表本身始终完整。
- **确认两步走**：第一次 `Enter` 只是上膛（按钮变成「确认释放 N 项」），第二次才真正关闭；`Esc` 随时退出。执行时会重新扫描一次，期间变活跃的 Pane 自动跳过。
- **级联回收**：关掉标签页里最后一个 Pane 会连标签页一起收，关掉工作区里最后一个标签页会连工作区一起收，面板里提前用 `连带释放 workspace「…」` 标出来。

网页端是同一套引擎：左栏 `释放闲置` 按钮或按 `x` 打开，勾选后点「释放选中」。

**顺带做全局磁盘清理**：面板底部有 `磁盘预览 d` / `磁盘清理 D` 两个按钮（键盘同名），把磁盘侧交给 [Mole](https://mole.fit) 的 `mo clean`：

- `d` → `mo clean --dry-run`（只看能清多少，不动文件）
- `D` → `mo clean`（真清，后续由 mo 自己确认）
- 两者都是**新开一个 herdr 标签页跑**，然后把你送过去、关掉看板。mo 是交互式工具（可能要 sudo、自带全屏 UI），必须待在真正的终端里，看板不代管它的输入输出。
- 没装 mo 时面板红字提示 `未找到 mo（Mole）· https://mole.fit`，不会有任何副作用。用 `HERDR_PORTAL_MO_BIN` 可指定别的可执行文件。

分工很清楚：**释放闲置 = 收内存和进程（pane/tab/workspace），mo clean = 收磁盘（缓存、日志、残留）**。

### 重命名（Pane / Tab / Workspace）

选中一张卡片后按 `E`（面板里的胶囊也能点）：

| 对象 | 改的是什么 | 空值 |
| --- | --- | --- |
| **Pane 标题** | 卡片上那行大标题（herdr 的 pane label，优先级高于终端标题） | 留空保存 = 清除自定义标题，回落到终端标题 |
| **Tab 名称** | 所在标签页的名字，**并把当前 Pane 标题一起改成同名**（同一个 Tab 里的其他 Pane 不动） | 不允许，面板会红字提示 |
| **Workspace 名称** | 所在工作区的名字 | 不允许，面板会红字提示 |

输入框支持 `←→` 移动光标、`Backspace` / `Delete` 删除、`Ctrl+U` 清空、中文直接输入；`Enter` 保存并立即刷新看板，`Esc` 原样退出。名称会去掉控制字符、压平空白，最长 80 字符。

改 Tab 名会连带改当前 Pane 标题，是因为卡片标题优先取 pane label：只改一半，同一张卡上会同时挂着新 Tab 名和旧 Pane 名。同步失败时 Tab 名照样保存，提示条会写明 `Pane 标题没跟上（原因）`。

### 版本检查与更新引导

看板标题行常驻当前版本（`全局智能体调度 · AGENT 看板 · v1.2.0`，取自 `herdr-plugin.toml`）。有新版时右上角多出一颗琥珀色 `⬆ 更新 vX.Y.Z  U` 按钮，键盘按 `U` 等效：

- **不阻塞**：启动时后台线程去读上游 `herdr-plugin.toml` 的版本号，结果缓存在 `~/.cache/herdr-portal/version.json`，默认 6 小时过期。渲染只读缓存，离线 / 限流只会让按钮不出现，不会卡看板一帧
- **按两次才动手**：第一次 `U` 只是提示 `发现新版 vX.Y.Z（当前 vA.B.C）· 再按一次 U 执行 …`，第二次才真正启动更新
- **更新方式跟安装方式一致**：插件目录里有 `.git` 就跑 `git pull --ff-only`（不会覆盖你的本地改动，冲突时命令自己失败并保留现场），否则跑 `herdr plugin install github:<repo>`
- **在真终端里跑**：更新命令新开一个 herdr 标签页执行，然后把你送过去、关掉看板——认证、冲突、交互提示都归你处理，看板不代管
- **已是最新 / 查不到**：分别提示 `已是最新 · vX.Y.Z` 和 `查不到最新版本 · 原因`，都不会有任何副作用

可调环境变量：`HERDR_PORTAL_REPO`（默认 `loofare/herdr-portal`）、`HERDR_PORTAL_BRANCH`（默认 `main`）、`HERDR_PORTAL_VERSION_TTL`（秒，默认 21600）。

## 快捷键速查

### TUI

| 键 | 作用 |
| --- | --- |
| `↑ ↓ ← →` / `hjkl` | 选择卡片 / 切换列 |
| `Enter` | 跳转到该 Pane 并关闭面板 |
| `Tab` / `v` | Agent 看板 ↔ 窗口视图 |
| `1-3` | 直选列 |
| `r` | 立即刷新 |
| `x` | 打开「释放闲置」回收面板 |
| `e` | 重命名 Pane 标题 / Tab / Workspace |
| `n` / `N` | 在选中卡片的工作区新开标签页（继承目录） |
| `s` / `S` | 在选中 Pane 右侧 / 下方新开 Pane（继承目录） |
| `u` / `U` | 检查版本；有新版时再按一次执行更新命令 |
| `q` / `Esc` | 退出面板 |

回收面板内：`↑↓` 移动 · `Space` 选中 · `A` 全选 · `N` 清空 · `T` 预选阈值 · `R` 重扫 · `d`/`D` 磁盘预览 / 清理（mo clean）· `Enter` 释放（按两次）· `Esc` 返回

重命名面板内：`Tab` 切换对象 · `←→` 移动光标 · `Ctrl+U` 清空 · `Enter` 保存 · `Esc` 取消

### 网页端

| 操作 | 效果 |
| --- | --- |
| 点击卡片 | 定位 Herdr 到该 Pane，并把终端窗口带到前台 |
| 点击卡片右上角 `↩` | 展开回复区（输入框 + 最近输出） |
| `Enter` / `Shift+Enter` / `Esc` | 发送 / 换行 / 收起回复区 |
| `x` / 左栏「释放闲置」 | 打开回收面板（输入框内打字不会误触发） |
| 左侧底部「浅色 / 深色 / 霓虹 / 指挥」 | 四种主题切换（默认指挥，记忆选择） |
| 「状态看板 / 工作区 / 窗口」 | 三种视图切换 |

## 使用场景

- **多项目并行监控**：几个 Agent 同时跑在不同 workspace，看板一眼看清谁在执行、谁在等你，一下按键或一次点击直达现场
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
  tui.py          # curses TUI 看板（键盘 + 鼠标）
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
