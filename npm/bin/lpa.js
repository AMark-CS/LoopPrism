#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const claude = require('../lib/claude');
const { atomicWrite } = require('../lib/fsutil');
const codex = require('../lib/codex');
const workbuddy = require('../lib/workbuddy');
const opencode = require('../lib/opencode');
const dsh = require('../lib/dsh');
const gemini = require('../lib/gemini');
const cursor = require('../lib/cursor');
const { configPath } = require('../plugin/scripts/config');
const viewer = require('../plugin/scripts/viewer');
const { version } = require('../package.json');

const HELP = `lpa ${version}: LoopPrism for Claude Code and Codex

Usage
  lpa install [claude|codex|workbuddy|opencode|dsh|gemini|cursor|all] [--url <api-url>]   add the hooks (default: all that are found)
  lpa uninstall [claude|codex|workbuddy|opencode|dsh|all]                   remove them
  lpa status                                         is LoopPrism up? latest runs
  lpa open                                           open the desktop app or dashboard

The hooks send each prompt, tool call and error to the LoopPrism API
(default http://127.0.0.1:8080). Set LOOPPRISM_URL to change it; the hooks do
nothing, and never slow the agent, when LoopPrism is not running.
Set LOOPPRISM_NO_PROMPTS=1 to keep prompt text out of the recorded runs.`;

function parse(argv) {
  const out = { command: argv[0], targets: [], url: null };
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] === '--url') out.url = argv[++i];
    else out.targets.push(argv[i]);
  }
  return out;
}

function pick(targets) {
  const all = !targets.length || targets.includes('all');
  return {
    claude: all || targets.includes('claude'),
    codex: all || targets.includes('codex'),
    workbuddy: all || targets.includes('workbuddy'),
    opencode: all || targets.includes('opencode'),
    dsh: all || targets.includes('dsh'),
    gemini: all || targets.includes('gemini'),
    cursor: all || targets.includes('cursor'),
    explicit: !all,
  };
}

function saveUrl(url) {
  const file = configPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  atomicWrite(file, `${JSON.stringify({ url }, null, 2)}\n`);
}

async function main(argv) {
  const { command, targets, url } = parse(argv);
  const want = pick(targets);

  if (command === 'status') return viewer.status();
  if (command === 'open') return viewer.open();

  if (command === 'install') {
    let failed = false;
    if (url) saveUrl(url);
    if (want.claude) {
      if (!claude.available()) {
        console.log('Claude Code: `claude` not found on PATH, skipped.');
        failed ||= want.explicit;
      } else {
        try {
          claude.install();
          console.log('Claude Code: plugin "loopprism" installed. Restart Claude Code; try /loopprism:status');
        } catch (err) {
          console.error(`Claude Code: ${err.message}`);
          failed = true;
        }
      }
    }
    if (want.codex) {
      const r = codex.install();
      console.log(`Codex: hooks written to ${r.file}`);
      console.log('       Open Codex and run /hooks once to review and trust them.');
    }
    if (want.workbuddy) {
      if (!workbuddy.available() && !want.explicit) {
        console.log('WorkBuddy: not found (no ~/.workbuddy), skipped.');
      } else {
        try {
          const r = workbuddy.install();
          console.log(`WorkBuddy: hooks written to ${r.file}`);
          console.log('           Restart WorkBuddy so it picks them up. Node.js must be on its PATH.');
        } catch (err) {
          console.error(`WorkBuddy: ${err.message}`);
          failed = true;
        }
      }
    }
    if (want.opencode) {
      if (!opencode.available() && !want.explicit) {
        console.log('OpenCode: not found, skipped.');
      } else {
        try {
          const r = opencode.install();
          console.log(`OpenCode: plugin written to ${r.file}`);
          console.log('          Restart OpenCode so it loads the plugin.');
        } catch (err) {
          console.error(`OpenCode: ${err.message}`);
          failed = true;
        }
      }
    }
    if (want.dsh) {
      if (!dsh.available() && !want.explicit) {
        console.log('DeepSeek Harness: not found (no ~/.dsh), skipped.');
      } else {
        const r = dsh.install();
        console.log(`DeepSeek Harness: hooks file written to ${r.file}`);
        console.log('                  In DSH Desktop, install the plugin dsh-hooks-claude-code, set its configPath to that file, and restart.');
      }
    }
    if (want.gemini) {
      if (!gemini.available() && !want.explicit) {
        console.log('Gemini CLI: not found (no ~/.gemini), skipped.');
      } else {
        try {
          const r = gemini.install();
          console.log(`Gemini CLI: hooks written to ${r.file}`);
          console.log('            Restart Gemini CLI so it picks them up. Node.js must be on its PATH.');
        } catch (err) {
          console.error(`Gemini CLI: ${err.message}`);
          failed = true;
        }
      }
    }
    if (want.cursor) {
      if (!cursor.available() && !want.explicit) {
        console.log('Cursor: not found, skipped.');
      } else {
        try {
          const r = cursor.install();
          console.log(`Cursor: hooks written to ${r.file}`);
          console.log('        Cursor reloads hooks.json by itself; Node.js must be on its PATH.');
        } catch (err) {
          console.error(`Cursor: ${err.message}`);
          failed = true;
        }
      }
    }
    console.log('\nNext: start LoopPrism (desktop app, or `lprism proxy`), then use your agent. `lpa status` shows the runs.');
    return failed ? 1 : 0;
  }

  if (command === 'uninstall') {
    if (want.claude && claude.available()) claude.uninstall();
    if (want.codex) codex.uninstall();
    if (want.workbuddy && workbuddy.available()) workbuddy.uninstall();
    if (want.opencode) opencode.uninstall();
    if (want.dsh) dsh.uninstall();
    if (want.gemini && gemini.available()) gemini.uninstall();
    if (want.cursor && cursor.available()) cursor.uninstall();
    console.log('LoopPrism hooks removed.');
    return 0;
  }

  console.log(HELP);
  return command && command !== 'help' && command !== '--help' && command !== '-h' ? 2 : 0;
}

main(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (err) => {
    console.error(err.message);
    process.exit(1);
  },
);
