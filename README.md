<p align="center">
  <h1 align="center">LoopPrism</h1>
  <p align="center"><em>See what your agents actually do.</em></p>
</p>

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
loopprism proxy --port 4317
```

Then open `http://localhost:8080` and watch every MCP call appear in real time.

## Features

- **Waterfall traces** — See every MCP tool call with timing, result size, and error state
- **MCP-native** — Understands `tools/call`, `tools/list`, `prompts/get`, and more
- **Cost breakdown** — Know which tool generates the most data
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
loopprism proxy --port 4317

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

## Architecture

```
Agent ──▶ loopprism Proxy ──▶ MCP Server
              │
              ├── Intercepts JSON-RPC
              ├── Extracts tool name, args, latency
              ├── Writes to SQLite (~/.loopprism/traces.db)
              └── Serves Dashboard (http://localhost:8080)
```

## Commands

```bash
# Start proxy + built-in dashboard (default)
loopprism proxy

# Custom ports
loopprism proxy --port 4317 --dashboard-port 8080

# Proxy only (no dashboard)
loopprism proxy --no-dashboard

# Standalone dashboard (connect to a remote DB)
loopprism dashboard --db ~/.loopprism/remote.db

# Analyze a specific trace
loopprism analyze <trace-id>

# Debug verbose mode
loopprism proxy --verbose
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

LoopPrism was previously named toolglass. The Python package and primary CLI are now `loopprism`. The `toolglass` CLI alias, `TOOLGLASS_*` environment variables, and incoming `X-Toolglass-*` headers remain supported. New environment variables use `LOOPPRISM_*` and take precedence. Existing `~/.toolglass/traces.db` and `config.toml` are used when their new equivalents are absent; no data is moved or deleted.

Install from GitHub for now; this repository does not yet provide a published `loopprism` PyPI release.

## License

MIT
