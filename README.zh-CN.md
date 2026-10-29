<h1 align="center"><img src="docs/assets/loopprism-logo.png" alt="" width="72" align="absmiddle">&nbsp;LoopPrism</h1>

<p align="center">
  Claude Code、Codex、OpenCode、DeepSeek Harness、WorkBuddy 的会话检查器：逐步查看每一次会话。<br>
  上下文被什么占满、时间花在哪、花了多少钱。本地优先，零配置。
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <a href="https://github.com/AMark-CS/LoopPrism/releases/latest"><b>下载</b></a> ·
  <a href="#功能">功能</a> ·
  <a href="#开始使用">开始使用</a>
</p>

<p align="center">
  <img src="docs/assets/loopprism-tour.gif" alt="LoopPrism 演示：对话、轨迹、上下文、子代理、花费" width="860">
</p>

<table>
  <tr>
    <td width="50%"><img src="docs/assets/inspector-chat.png" alt="对话视图"></td>
    <td width="50%"><img src="docs/assets/inspector-trajectory.png" alt="轨迹视图"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>对话</b>：完整对话，每次工具调用可展开</sub></td>
    <td align="center"><sub><b>轨迹</b>：时间线上的每一步，自动标出重复调用和连续失败</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/assets/inspector-context.png" alt="上下文视图"></td>
    <td width="50%"><img src="docs/assets/inspector-agents.png" alt="子代理视图"></td>
  </tr>
  <tr>
    <td align="center"><sub><b>上下文</b>：上下文被什么占满，时间和钱花在哪</sub></td>
    <td align="center"><sub><b>子代理</b>：子代理的分支与合并，以及它们之间传递的内容</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/assets/inspector-cost.png" alt="花费页面"></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><sub><b>花费</b>：所有应用、所有会话的总花费，一页看清</sub></td>
  </tr>
</table>

## 功能

- 🗂 **会话**：读取本机所有 Claude Code、Codex、OpenCode、DeepSeek Harness、WorkBuddy 会话。可搜索全部消息，按日期或项目分组，导出 Markdown。Claude Code 和 Codex 的会话还可以直接恢复、移入回收站；其余应用为只读。
- 🧭 **轨迹**：每一步（提示词、注入的上下文、思考、工具调用、结果）都在时间线上，带耗时与搜索，并标出重复调用和连续失败。
- 🧮 **上下文**：模型输入的每一部分来自哪里：系统提示词、工具定义、你的消息、注入内容、技能、工具结果。含窗口占用、趋势和缓存命中率。
- 💸 **花费**：按各厂商公开的 API 价格，把真实 token 用量换算成美元，可按 token 类型、模型、每一轮拆分。**花费**页汇总所有应用：按天、模型、应用、项目统计，并列出最贵的会话。
- 🤖 **子代理**：把主代理画成一条线，子代理分支出去再合并回来，显示任务、返回值、花费和并行程度（Claude Code）。
- ⚡ **优化**：找出花得多于必要的地方（缓存命中低、简单任务用了大模型、重复调用、超大工具输出、过长会话），估算每条建议能省多少，并给出占总花费的比例。标记“已采纳”后，会对比采纳前后的单次调用成本；还会从 GitHub 推荐开源的省 token 工具。可选的 AI 分析使用你自己配置的模型地址和 API key，发送前会展示完整内容，且只发汇总数字。
- 🎨 **主题与语言**：深色、浅色或跟随系统；界面支持 English / 简体中文（或跟随系统）。都在“设置”里选择，对整个应用（含仪表盘）生效。
- 🔌 **MCP 追踪与实时运行**：可选的代理会记录每一次 MCP 工具调用；hooks 实时记录代理正在做什么。

一切都留在你的电脑上：SQLite 存本地，无需 Docker、云服务或账号。

## 支持的应用与模型

LoopPrism 支持 **macOS** 和 **Windows**，两个平台功能一致。

| 应用 | 会话（从磁盘读取） | 实时运行（hooks） | 在此恢复 / 删除 |
|---|---|---|---|
| **Claude Code** | `~/.claude/projects`（含子代理） | 支持，插件 | 支持 |
| **Codex** | `~/.codex/sessions` | 支持，`~/.codex/hooks.json` | 支持 |
| **OpenCode** | `~/.local/share/opencode/opencode.db` | 支持，插件 `~/.config/opencode/plugins` | 只读 |
| **DeepSeek Harness**（`dsh`） | `~/.dsh/sessions`（zstd），`$DSH_HOME` | 支持，经其钩子插件（需手动一步） | 只读 |
| **WorkBuddy** | `~/.workbuddy/projects`，`$WORKBUDDY_CONFIG_DIR` | 支持，`~/.workbuddy/settings.json` | 只读 |

花费按各模型公开的按量 API 价格计算（缓存读写分别计价）。内置：**Claude**、**OpenAI**（GPT-6、GPT-5、Codex 系列）、**DeepSeek**、**MiniMax**、**GLM**（4.5 到 5.x）、**Qwen**、**Kimi**、**Gemini**，以及 OpenCode Zen 的 `-free` 免费模型。较新的版本按同系列已知的最新价格估算；没有价格的模型显示“无价格”，不计入总额。可在 `~/.loopprism/pricing.json` 中自定义或修正任意价格。花费是“按 API 计价的估算”，订阅和免费额度的实际计费不同。

## 开始使用

### 桌面应用（macOS 和 Windows，推荐）

- **macOS**：从[最新发布](https://github.com/AMark-CS/LoopPrism/releases/latest)下载 `.dmg`（Apple 芯片选 `arm64`，Intel 选 `x64`），拖到“应用程序”。首次打开：右键应用 → **打开**（暂未公证），或运行 `xattr -dr com.apple.quarantine /Applications/LoopPrism.app`。
- **Windows (x64)**：下载 `LoopPrism-<版本>-x64.exe` 并运行，可选择安装目录，以及仅为自己安装（默认，无需管理员权限）还是为所有用户安装。尚未代码签名，SmartScreen 可能提示，点 **更多信息 → 仍要运行**。

应用自带全部依赖，无需 Python 或终端；它会在菜单栏（macOS）或系统托盘（Windows）中保持运行。

### 命令行

```bash
pip install "git+https://github.com/AMark-CS/LoopPrism.git"
lprism proxy        # 然后打开 http://localhost:8080
```

### 为 Claude Code、Codex、WorkBuddy、OpenCode、DeepSeek Harness 开启实时运行

```bash
npx loopprism install     # 为你已安装的应用添加 hooks
lpa status                # 查看最新运行
```

Codex 安装后需运行一次 `/hooks` 以信任这些 hooks；WorkBuddy 和 OpenCode 安装后需重启（OpenCode 装的是一个单文件插件）。DeepSeek Harness 需要多一步手动：`lpa install dsh` 会生成 `~/.loopprism/dsh-hooks.json`，再在 DSH Desktop 里安装插件 `dsh-hooks-claude-code`，把它的 `configPath` 设为该文件并重启。详见 [npm/README.md](npm/README.md)。

## 许可证

[MIT](./LICENSE)
