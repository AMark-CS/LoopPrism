'use strict';
// DeepSeek Harness: it runs Claude Code style hook files through its official bridge plugin,
// `@deepseek-ai/dsh-hooks-claude-code`, whose `configPath` points at a hooks.json. We write that
// file (~/.loopprism/dsh-hooks.json) and never touch DeepSeek Harness's own profile: installing the
// plugin and setting `configPath` happens in DSH Desktop's plugin page.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { packageRoot, stableDirs } = require('./paths');
const { atomicWrite } = require('./fsutil');
const { hooksInUse } = require('./shared');

const MARKER = path.join('.loopprism', 'hooks', 'hook.js');
// The bridge supports these four Claude Code events (no failure or end events).
const EVENTS = ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop'];

const hooksFile = (home = os.homedir()) => path.join(stableDirs(home).base, 'dsh-hooks.json');
const dshHome = (env = process.env, home = os.homedir()) => env.DSH_HOME || path.join(home, '.dsh');

/** DeepSeek Harness or its desktop app is here: ~/.dsh exists once it has run; the app may not have yet. */
function available({ home, env = process.env } = {}) {
  return fs.existsSync(dshHome(env, home)) || (process.platform === 'darwin' && fs.existsSync('/Applications/DSH Desktop.app'));
}

function install({ home, env = process.env } = {}) {
  const dirs = stableDirs(home);
  fs.rmSync(dirs.hooks, { recursive: true, force: true });
  fs.cpSync(path.join(packageRoot, 'plugin', 'scripts'), dirs.hooks, { recursive: true });
  const command = `node "${path.join(dirs.hooks, 'hook.js')}" --agent dsh`;
  const hooks = {};
  for (const event of EVENTS) {
    const group = { hooks: [{ type: 'command', command, timeout: 5 }] };
    if (event === 'PostToolUse') group.matcher = '*';
    hooks[event] = [group];
  }
  const file = hooksFile(home);
  atomicWrite(file, `${JSON.stringify({ description: 'LoopPrism hooks for DeepSeek Harness', hooks }, null, 2)}\n`);
  return { file };
}

function uninstall({ home, env = process.env } = {}) {
  const file = hooksFile(home);
  fs.rmSync(file, { force: true });
  if (!hooksInUse('dsh', { home, env })) fs.rmSync(stableDirs(home).hooks, { recursive: true, force: true });
  return { file };
}

function isInstalled({ home } = {}) {
  try {
    return JSON.stringify(JSON.parse(fs.readFileSync(hooksFile(home), 'utf8'))).includes(MARKER.replace(/\\/g, '\\\\'));
  } catch {
    return false;
  }
}

module.exports = { available, install, uninstall, isInstalled, hooksFile, MARKER };
