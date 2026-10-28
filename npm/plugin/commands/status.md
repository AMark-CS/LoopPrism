---
description: Show the latest runs LoopPrism recorded from your agent sessions
allowed-tools: 'Bash(node "${CLAUDE_PLUGIN_ROOT}/scripts/viewer.js" status)'
---

Run this command and show its output as-is, then add one line pointing out any run with errors or an `abandoned` status:

```
node "${CLAUDE_PLUGIN_ROOT}/scripts/viewer.js" status
```

If it says LoopPrism is not running, tell the user to start the LoopPrism desktop app or run `lprism proxy`.
