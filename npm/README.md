# LoopPrism for Claude Code and Codex

Records every prompt, tool call and error from your coding agent as **runs** in
[LoopPrism](https://github.com/AMark-CS/LoopPrism), so you can see what the agent
actually did: built-in tools and shell commands included, not only MCP calls.

```bash
npx loopprism install          # Claude Code and/or Codex, whichever is installed
```

or install once and use the short command:

```bash
npm install -g loopprism
lpa install
```

| Command | What it does |
|---|---|
| `lpa install [claude\|codex\|all]` | Add the hooks. Claude Code gets a plugin (`/loopprism:status`, `/loopprism:open`); Codex gets entries in `~/.codex/hooks.json`. |
| `lpa uninstall [claude\|codex\|all]` | Remove them. Other hooks in your config are left alone. |
| `lpa status` | Is LoopPrism up? The newest runs. |
| `lpa open` | Open the desktop app, or the dashboard in your browser. |

You also need LoopPrism running to receive the events: the desktop app, or `lprism proxy`.

## Notes

- **Codex asks you to trust new hooks.** After `lpa install`, open Codex and run `/hooks` once to review and trust them.
- **Claude Code without npm:** `/plugin marketplace add AMark-CS/LoopPrism`, then `/plugin install loopprism@loopprism`.
- **It never slows your agent.** The hook gives up after one second, backs off for ten seconds after a failure, always exits 0, and does nothing when LoopPrism is not running.
- **Privacy:** events go only to your own LoopPrism (`http://127.0.0.1:8080`; set `LOOPPRISM_URL` or `lpa install --url ...` to change it). Set `LOOPPRISM_NO_PROMPTS=1` to keep prompt text out of the recorded runs. Long tool inputs and outputs are cut before they are sent. Set `LOOPPRISM_DISABLE=1` to turn the hooks off.
- **Cost:** when a turn ends, the hook reads the token counts and model names for that turn from the agent's own session transcript (never its text) and sends only those. LoopPrism prices them at the provider's current API list prices (`~/.loopprism/pricing.json` overrides a model's price). It is an estimate of what the turn would cost on the API; subscription plans (Claude Pro/Max, ChatGPT) bill differently, and models without a published price show no cost.
- **What a run is:** one user prompt up to the agent's `Stop`. A run still open when the next prompt or the session end arrives is marked `abandoned`.
- Requires Node 18 or newer. macOS and Linux are tested; Windows is untested.

## How it works

```
Claude Code / Codex --hook event (stdin JSON)--> hook.js --POST /api/ingest/events--> LoopPrism
```

The same `hook.js` serves both agents (`--agent claude-code|codex`); their hook payloads share the fields it reads.
