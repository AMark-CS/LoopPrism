#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const claude = require('../lib/claude');
const codex = require('../lib/codex');
const { configPath } = require('../plugin/scripts/config');
const viewer = require('../plugin/scripts/viewer');
const { version } = require('../package.json');

const HELP = `lpa ${version}: LoopPrism for Claude Code and Codex

Usage
  lpa install [claude|codex|all] [--url <api-url>]   add the hooks (default: all that are found)
  lpa uninstall [claude|codex|all]                   remove them
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
  return { claude: all || targets.includes('claude'), codex: all || targets.includes('codex'), explicit: !all };
}

function saveUrl(url) {
  const file = configPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify({ url }, null, 2)}\n`);
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
    console.log('\nNext: start LoopPrism (desktop app, or `lprism proxy`), then use your agent. `lpa status` shows the runs.');
    return failed ? 1 : 0;
  }

  if (command === 'uninstall') {
    if (want.claude && claude.available()) claude.uninstall();
    if (want.codex) codex.uninstall();
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
