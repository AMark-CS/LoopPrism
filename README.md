<h1 align="center"><img src="docs/assets/loopprism-logo.png" alt="LoopPrism logo" width="64" align="absmiddle"> LoopPrism</h1>

<p align="center"><em>See what your agents actually do.</em></p>

<p align="center">
  <a href="https://github.com/AMark-CS/LoopPrism"><img src="https://img.shields.io/badge/python-3.10+-blue?logo=python" alt="Python"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-black" alt="License"></a>
</p>

---

## What is LoopPrism?

LoopPrism is the **`strace` for AI agents**. It sits between your agent and
MCP servers, recording every tool call so you can see exactly what happened,
how long it took, and where your token budget is going.

> No code changes. Just point your MCP clients at loopprism.

```bash
pip install "git+https://github.com/AMark-CS/LoopPrism.git"
lprism proxy --port 4317
```

Then open `http://localhost:8080` and watch every MCP call appear in real time.

**Three ways to use it** (they share one trace database, `~/.loopprism/traces.db`):

| You want | Use |
|---|---|
| A double-click app, no Python or terminal | [Desktop app](#desktop-app-macos) |
| See what Claude Code or Codex did (every tool call, not only MCP) | [`npx loopprism install`](#claude-code-and-codex) |
| See calls from MCP clients, or run it headless | `lprism proxy` (above) |

## Features

- **Waterfall traces** — See every MCP tool call with timing, result size, and error state
- **MCP-native** — Understands `tools/call`, `tools/list`, `prompts/get`, and more
- **Estimated cost** — Agent runs are priced from their real token usage at the providers' current API prices (an API-equivalent estimate; subscription plans bill differently)
- **Zero config** — One command, SQLite on disk, no Docker, no cloud
- **Local-first** — All data stays on your machine

## Quick Start

### 1. Install

```bash
pip install "git+https://github.com/AMark-CS/LoopPrism.git"
# or: uv tool install git+https://github.com/AMark-CS/LoopPrism.git
```

### 2. Start the proxy

```bash
lprism proxy --port 4317

╭─────────────────────────────────────────────────────╮
│              loopprism                              │
│      "See what your agents actually do"            │
├─────────────────────────────────────────────────────┤
│  Proxy:     http://localhost:4317                   │
│  Dashboard: http://localhost:8080                   │
│  Database:  ~/.loopprism/traces.db                  │
│                                                     │
│  Ready. Point your MCP clients to localhost:4317   │
╰─────────────────────────────────────────────────────╯
```

### 3. Point your MCP clients to loopprism

```jsonc
// Claude Desktop config (~/.claude/settings.json)
{
  "mcpServers": {
    "github": {
      "url": "http://localhost:4317/github?backend=https://api.github.com/mcp"
    },
    "filesystem": {
      "url": "http://localhost:4317/fs?backend=http://localhost:3001"
    }
  }
}
```

Or via environment variable:

```bash
export GITHUB_MCP_URL="http://localhost:4317/github?backend=https://api.github.com/mcp"
```

### 4. Open the dashboard

Visit `http://localhost:8080` — every MCP tool call appears in real time with:
- Waterfall chart showing timing and latency
- Cost breakdown by tool
- MCP server health stats

## Desktop app (macOS)

Download the latest `.dmg` from the
[Releases page](https://github.com/AMark-CS/LoopPrism/releases/latest): `arm64` for Apple
Silicon, `x64` for Intel. Drag **LoopPrism** into Applications and open it. It bundles the
proxy and the dashboard (no Python needed), shows the dashboard in a window, and keeps
running from the menu bar. On first launch it connects Claude Code and Codex for you (switch
them off or on later in the **Apps** page), so there is nothing to install or configure; it also
reuses a `lprism proxy` you already have running instead of starting a second one.

The app is not signed or notarized yet, so macOS blocks the first launch: right-click the
app and choose **Open**, or run `xattr -dr com.apple.quarantine /Applications/LoopPrism.app`.
Point MCP clients at `http://127.0.0.1:4317/<server-name>` (the menu bar icon has
**Copy proxy URL**). More in [desktop/README.md](desktop/README.md).

## Session inspector

The desktop app (and `http://127.0.0.1:8080` when you run `lprism proxy`) opens on **Sessions**: every
Claude Code and Codex session on your machine, read straight from their own session files, with
nothing to install or configure.

- **Sessions**: search across all of them, group by day or project, resume a session in Terminal
  (or copy the `claude --resume` / `codex resume` command), export to Markdown, move to the Trash.
- **Chat**: the conversation, tool calls expandable.
- **Trajectory**: a timeline of every step (prompt, injected context, thinking, tool call, result)
  with durations, search, and flagged patterns such as the same tool called again and again.
- **Context**: what filled the model's input at each step (system prompt, tool schemas, your
  messages, injected context, tool results), the context-window fill, a trend over the session, cache
  hit rate, cost at current API prices and where the time went. For Claude Code 2.1.308 and newer
  the exact requests are recorded in the session file, so the breakdown is exact; for older sessions
  the system prompt and tool schemas are inferred.

Session content never leaves your machine, and these endpoints only answer requests from your own
dashboard.

## Claude Code and Codex

The MCP proxy only sees MCP calls. To record everything a coding agent does (shell
commands, file edits, built-in tools, and the prompt behind each piece of work), install
the hooks:

```bash
npx loopprism install      # Claude Code and/or Codex, whichever is installed
lpa status                 # newest runs (after: npm install -g loopprism)
```

Start LoopPrism first (the desktop app, or `lprism proxy`), then restart your agent. In Codex,
run `/hooks` once to trust the new hooks. Claude Code can also use the plugin directly: `/plugin marketplace add AMark-CS/LoopPrism`,
then `/plugin install loopprism@loopprism`. Details, privacy options and uninstall are in
[npm/README.md](npm/README.md). Each prompt becomes a run; tool calls become spans.

## Architecture

```
Agent ──▶ LoopPrism Proxy ──▶ MCP Server
              │
              ├── Intercepts JSON-RPC
              ├── Extracts tool name, args, latency
              ├── Writes to SQLite (~/.loopprism/traces.db)
              └── Serves Dashboard (http://localhost:8080)
```

Current layers, top to bottom (capture, trace core, analysis, API / dashboard / CLI, packaging):

![LoopPrism architecture, current state](docs/assets/architecture-current.png)

Where it is heading, with built and planned pieces (solid vs dashed):

![LoopPrism stages, built vs planned](docs/assets/architecture-stages.png)

Source files are in Figma: [LoopPrism architecture](https://www.figma.com/design/RZP1ns1hfsPffaEZFOYlqt) (private to the author's team until shared). Data model details: [docs/run-data-model.md](docs/run-data-model.md).

## Commands

```bash
# Start proxy + built-in dashboard (default)
lprism proxy

# Custom ports
lprism proxy --port 4317 --dashboard-port 8080

# Proxy only (no dashboard)
lprism proxy --no-dashboard

# Standalone dashboard (connect to a remote DB)
lprism dashboard --db ~/.loopprism/remote.db

# Analyze a specific trace
lprism analyze <trace-id>

# Debug verbose mode
lprism proxy --verbose
```

## API

The dashboard is backed by a REST API:

| Endpoint | Description |
|----------|-------------|
| `GET /api/traces` | List traces |
| `GET /api/traces/:id` | Get trace with all spans |
| `GET /api/mcp-servers` | Stats per MCP server |
| `GET /api/mcp-tools` | Stats per tool |
| `GET /api/cost/summary` | Cost overview |
| `GET /api/cost/trace/:id` | Cost breakdown per trace |
| `GET /api/health` | Health check |

## Development

```bash
git clone git@github.com:AMark-CS/LoopPrism.git
cd LoopPrism
pip install -e ".[dev]"
pytest

# Dashboard dev server
cd dashboard
npm install
npm run dev
```

## Rename compatibility

LoopPrism was previously named toolglass. The Python package is `loopprism` and the CLI command is `lprism`; the former `toolglass` and `loopprism` commands no longer exist. `TOOLGLASS_*` environment variables and incoming `X-Toolglass-*` headers remain supported. New environment variables use `LOOPPRISM_*` and take precedence. Existing `~/.toolglass/traces.db` and `config.toml` are used when their new equivalents are absent; no data is moved or deleted.

Install from GitHub for now; this repository does not yet provide a published `loopprism` PyPI release.

## License

MIT
