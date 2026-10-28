#!/usr/bin/env node
'use strict';
// `status` and `open` for the slash commands and the `lpa` CLI.
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { baseUrl } = require('./config');

async function api(pathname, url = baseUrl()) {
  const res = await fetch(`${url}${pathname}`, { signal: AbortSignal.timeout(2000) });
  if (!res.ok) throw new Error(`HTTP ${res.status} from ${pathname}`);
  return res.json();
}

function downMessage(url) {
  return (
    `LoopPrism is not running at ${url}.\n` +
    'Start the desktop app, or run:  lprism proxy\n' +
    '(set LOOPPRISM_URL if it listens somewhere else)'
  );
}

/** Print the newest runs. Returns the process exit code. */
async function status(log = console.log, url = baseUrl()) {
  let traces;
  try {
    await api('/api/health', url);
    ({ traces } = await api('/api/traces?limit=8', url));
  } catch {
    log(downMessage(url));
    return 1;
  }
  log(`LoopPrism at ${url} is up. Dashboard: ${url}/`);
  if (!traces.length) {
    log('No runs recorded yet.');
    return 0;
  }
  log('');
  for (const t of traces) {
    let agent = '';
    try {
      agent = (JSON.parse(t.tags || '{}').agent || '').padEnd(11);
    } catch {
      agent = ''.padEnd(11);
    }
    const state = String(t.status || '?').padEnd(10);
    const name = (t.root_span_name || '').slice(0, 50);
    log(`${String(t.timestamp).slice(0, 19)}  ${state} ${agent} ${String(t.span_count).padStart(3)} spans ${String(t.error_count).padStart(2)} err  ${name}`);
  }
  return 0;
}

function launcher() {
  if (process.platform === 'darwin') return { cmd: 'open', pre: [] };
  if (process.platform === 'win32') return { cmd: 'cmd', pre: ['/c', 'start', ''] };
  return { cmd: 'xdg-open', pre: [] };
}

/** The installed desktop app, if any: the .app on macOS, the per-user install on Windows. */
function desktopApp(env = process.env) {
  const candidates =
    process.platform === 'darwin'
      ? ['/Applications/LoopPrism.app']
      : process.platform === 'win32' && env.LOCALAPPDATA
        ? [path.join(env.LOCALAPPDATA, 'Programs', 'LoopPrism', 'LoopPrism.exe')]
        : [];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

/** Open the desktop app if installed, otherwise the dashboard in the browser. */
async function open(log = console.log, url = baseUrl()) {
  const app = desktopApp();
  const { cmd, pre } = launcher();
  // Launching the exe again just brings the running app's window forward.
  const [run, args] = app ? (process.platform === 'darwin' ? [cmd, [app]] : [app, []]) : [cmd, [...pre, `${url}/`]];
  try {
    await api('/api/health', url);
  } catch {
    if (!app) {
      log(downMessage(url));
      return 1;
    }
  }
  spawn(run, args, { stdio: 'ignore', detached: true, windowsHide: true }).unref();
  log(app ? 'Opening the LoopPrism app.' : `Opening ${url}/`);
  return 0;
}

module.exports = { status, open, api };

if (require.main === module) {
  const [, , command] = process.argv;
  const run = command === 'open' ? open : command === 'status' ? status : null;
  if (!run) {
    console.error('usage: viewer.js status|open');
    process.exit(2);
  }
  run().then((code) => process.exit(code));
}
