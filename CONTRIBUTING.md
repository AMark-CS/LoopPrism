# Contributing

Thanks for helping! LoopPrism supports **macOS and Windows**, with the same features on both.

## Set up

```bash
git clone https://github.com/AMark-CS/LoopPrism.git && cd LoopPrism
pip install -e ".[dev]" && pytest          # Python backend
cd dashboard && npm ci && npm run dev      # dashboard
cd ../desktop && npm ci && npm test        # desktop app
cd ../npm && node --test                   # hooks and installers
```

Try the inspector on made-up sessions (not yours):

```bash
python scripts/make_demo_sessions.py /tmp/lp-demo
CLAUDE_CONFIG_DIR=/tmp/lp-demo/.claude CODEX_HOME=/tmp/lp-demo/.codex lprism proxy
```

## Adding support for another coding agent

An adapter turns the app's session files into LoopPrism's normalised session (see
`src/loopprism/sessions/models.py`). Copy the closest of `codex.py`, `workbuddy.py`, `opencode.py`
or `dsh.py`, register it in `sessions/store.py`, add a fixture in `tests/support_other_agents.py` and
tests next to it. Prices live in `src/loopprism/cost/pricing.py`.

## Before you open a PR

CI runs the Python, desktop and npm tests on macOS and Windows, builds the dashboard, and smoke-tests the
Windows installer. Please run the tests for the part you changed, and keep behaviour identical on both platforms.
