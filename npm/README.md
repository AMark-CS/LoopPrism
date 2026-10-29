# LoopPrism for Claude Code, Codex, Gemini CLI, WorkBuddy and OpenCode

Records every prompt, tool call and error from your coding agent as **runs** in
[LoopPrism](https://github.com/AMark-CS/LoopPrism), so you can see what the agent
actually did: built-in tools and shell commands included, not only MCP calls.

```bash
npx loopprism install          # Claude Code, Codex, WorkBuddy and/or OpenCode, whichever is installed
```

or install once and use the short command:

```bash
npm install -g loopprism
lpa install
```

| Command | What it does |
|---|---|
| `lpa install [claude\|codex\|gemini\|workbuddy\|opencode\|dsh\|all]` | Add the hooks. Claude Code gets a plugin (`/loopprism:status`, `/loopprism:open`); Codex gets entries in `~/.codex/hooks.json`; WorkBuddy gets entries in the `hooks` key of `~/.workbuddy/settings.json` (a copy of the original is kept next to it as `settings.json.loopprism.bak`); OpenCode gets one plugin file, `~/.config/opencode/plugins/loopprism.js` (or under `$OPENCODE_CONFIG_DIR`). |
| `lpa uninstall [claude\|codex\|gemini\|workbuddy\|opencode\|dsh\|all]` | Remove them. Other hooks in your config are left alone. |
| `lpa status` | Is LoopPrism up? The newest runs. |
| `lpa open` | Open the desktop app, or the dashboard in your browser. |

You also need LoopPrism running to receive the events: the desktop app, or `lprism proxy`.

## Notes

- **Codex asks you to trust new hooks.** After `lpa install`, open Codex and run `/hooks` once to review and trust them.
- **DeepSeek Harness:** `lpa install dsh` only writes `~/.loopprism/dsh-hooks.json`; it never edits DSH's own profile. In DSH Desktop install the plugin `dsh-hooks-claude-code`, set its `configPath` to that file, and restart. The bridge supports session start, prompt, tool and stop events (no tool failures).
- **Gemini CLI:** `lpa install gemini` adds hooks to the `hooks` key of `~/.gemini/settings.json` (`$GEMINI_CLI_HOME` moves the folder); restart Gemini CLI afterwards.
- **OpenCode:** restart it after `lpa install` so it loads the plugin. Uninstall removes only the file LoopPrism wrote.
- **WorkBuddy:** restart it after `lpa install` so it reads the hooks. They run `node`, so Node.js must be on the PATH WorkBuddy uses. `WORKBUDDY_CONFIG_DIR` points `lpa` at a different WorkBuddy folder.
- **Claude Code without npm:** `/plugin marketplace add AMark-CS/LoopPrism`, then `/plugin install loopprism@loopprism`.
- **It never slows your agent.** The hook gives up after one second, backs off for ten seconds after a failure, always exits 0, and does nothing when LoopPrism is not running.
- **Privacy:** events go only to your own LoopPrism (`http://127.0.0.1:8080`; set `LOOPPRISM_URL` or `lpa install --url ...` to change it). Set `LOOPPRISM_NO_PROMPTS=1` to keep prompt text out of the recorded runs. Long tool inputs and outputs are cut before they are sent. Set `LOOPPRISM_DISABLE=1` to turn the hooks off.
- **Cost:** when a turn ends, the hook reads the token counts and model names for that turn from the agent's own session transcript (never its text) and sends only those. LoopPrism prices them at the provider's current API list prices (`~/.loopprism/pricing.json` overrides a model's price). It is an estimate of what the turn would cost on the API; subscription plans (Claude Pro/Max, ChatGPT) bill differently, and models without a published price show no cost.
- **What a run is:** one user prompt up to the agent's `Stop`. A run still open when the next prompt or the session end arrives is marked `abandoned`.
- Requires Node 18 or newer. Supported on macOS and Windows, with the same commands and behaviour on both; `lpa` finds `claude` and `codex` through the shell (including the `.cmd` shims npm installs on Windows).

## How it works

```
Claude Code / Codex / WorkBuddy --hook event (stdin JSON)--> hook.js --POST /api/ingest/events--> LoopPrism
```

The same `hook.js` serves both agents (`--agent claude-code|codex`); their hook payloads share the fields it reads.
