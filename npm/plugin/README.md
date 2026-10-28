# LoopPrism for Claude Code

Shows what your agent actually did. This plugin records each prompt, tool call and error from
your Claude Code sessions as a **run** in [LoopPrism](https://github.com/AMark-CS/LoopPrism),
a local observability tool, so you can open a dashboard and see every step, how long it took,
and where it failed.

It needs LoopPrism running on your machine (the LoopPrism desktop app, or `lprism proxy`).
If LoopPrism is not running, the plugin does nothing and does not slow Claude Code down.

## What it runs

Six hooks run a small Node script (`scripts/hook.js`, no dependencies):

| Hook | Reported |
|---|---|
| `SessionStart`, `SessionEnd` | that a session started or ended |
| `UserPromptSubmit` | the text of your prompt |
| `PostToolUse`, `PostToolUseFailure` | the tool name, its input, a result or error, and how long it took |
| `Stop` | that Claude finished responding, plus the token counts and model names for that turn (see below) |

Two slash commands are included. `/loopprism:status` prints your newest runs and
`/loopprism:open` opens the dashboard. They run `scripts/viewer.js`, which only reads from
your LoopPrism server.

## What is sent, and where

Each hook sends one JSON event over HTTP to **`http://127.0.0.1:8080`** by default: your own
machine, the LoopPrism server. Nothing is sent anywhere else unless **you** point the plugin
at another address by setting `LOOPPRISM_URL` or by running `lpa install --url <address>`.

An event contains the session id, the working directory, the model name when Claude Code provides it, and, depending on
the hook, your prompt, or a tool's name, input and result. When Claude finishes a turn, the `Stop` hook opens **your session's own transcript file**
(the `transcript_path` Claude Code hands to hooks, under `~/.claude/projects/`) and reads only
the token usage numbers and model names from it, so LoopPrism can estimate what the turn cost.
The transcript's text is not sent. For Codex sessions the same hook reads the matching file
under `~/.codex/sessions/`.

Long values are cut before they are
sent (4,000 characters per string), and LoopPrism cuts them again when it stores them. Events
are stored in a SQLite file on your machine, `~/.loopprism/traces.db`.

The plugin reads only its own `LOOPPRISM_*` settings (and `CODEX_HOME`, to find Codex
sessions) from the environment, never reads credentials, never makes any other network
request, and never changes Claude Code's permission settings.

## Controls

| Setting | Effect |
|---|---|
| `LOOPPRISM_DISABLE=1` | turn the hooks off |
| `LOOPPRISM_NO_PROMPTS=1` | keep your prompt text out of the events |
| `LOOPPRISM_URL` | send events to a different LoopPrism address |
| `LOOPPRISM_DEBUG=1` | print problems to stderr |

The hook gives up after one second, backs off for ten seconds after a failure, and always
exits successfully, so it cannot block or fail your session.

## Install

```
/plugin marketplace add AMark-CS/LoopPrism
/plugin install loopprism@loopprism
```

or from a shell: `npx loopprism install` (this also sets up Codex).
Remove it with `/plugin uninstall loopprism@loopprism`.

MIT licensed. Source: https://github.com/AMark-CS/LoopPrism (this plugin is in `npm/plugin`).
