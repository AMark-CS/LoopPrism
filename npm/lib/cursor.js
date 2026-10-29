'use strict';
// Cursor: register LoopPrism's hook in ~/.cursor/hooks.json (`{"version": 1, "hooks": {event: [{command, ...}]}}`),
// merged and idempotent, and keep a copy of the hook scripts under ~/.loopprism/hooks. Cursor sends the
// conversation as conversation_id, the folder as workspace_roots and the tool result as tool_output;
// hook.js understands that. Timeouts are in seconds. The command uses an absolute path.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { packageRoot, stableDirs } = require('./paths');
const { atomicWrite, backupOnce } = require('./fsutil');

const MARKER = path.join('.loopprism', 'hooks', 'hook.js');
// Observe-only moments: a prompt was sent, a tool finished or failed, the agent stopped.
const WANTED = ['sessionStart', 'beforeSubmitPrompt', 'postToolUse', 'postToolUseFailure', 'stop', 'sessionEnd'];

const isOurs = (h) => typeof h.command === 'string' && h.command.includes(MARKER);
const cursorHome = (home = os.homedir()) => path.join(home, '.cursor');
const hooksFile = (home) => path.join(cursorHome(home), 'hooks.json');

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return {};
    throw new Error(`Cannot parse ${file}: ${err.message}. Fix or remove it, then retry.`);
  }
}

function stripOurs(config) {
  const hooks = config.hooks && typeof config.hooks === 'object' ? config.hooks : {};
  for (const [event, list] of Object.entries(hooks)) {
    if (!Array.isArray(list)) continue;
    hooks[event] = list.filter((h) => !isOurs(h));
    if (hooks[event].length === 0) delete hooks[event];
  }
  if (Object.keys(hooks).length === 0) delete config.hooks;
  else config.hooks = hooks;
  return config;
}

/** Is Cursor on this machine? ~/.cursor exists once it has run; the app may be installed before that. */
function available({ home } = {}) {
  return (
    fs.existsSync(cursorHome(home)) ||
    (process.platform === 'darwin' && fs.existsSync('/Applications/Cursor.app')) ||
    (process.platform === 'win32' && fs.existsSync(path.join(process.env.LOCALAPPDATA || '', 'Programs', 'cursor')))
  );
}

function install({ home } = {}) {
  const dirs = stableDirs(home);
  fs.rmSync(dirs.hooks, { recursive: true, force: true });
  fs.cpSync(path.join(packageRoot, 'plugin', 'scripts'), dirs.hooks, { recursive: true });
  const file = hooksFile(home);
  const config = stripOurs(readJson(file));
  config.version = config.version || 1;
  config.hooks = config.hooks || {};
  const command = `node "${path.join(dirs.hooks, 'hook.js')}" --agent cursor`;
  for (const event of WANTED) (config.hooks[event] ||= []).push({ command, timeout: 5 });
  backupOnce(file);
  atomicWrite(file, `${JSON.stringify(config, null, 2)}\n`);
  return { file };
}

function uninstall({ home, env = process.env } = {}) {
  const file = hooksFile(home);
  if (fs.existsSync(file)) {
    const config = stripOurs(readJson(file));
    atomicWrite(file, `${JSON.stringify(config, null, 2)}\n`);
  }
  if (!require('./shared').hooksInUse('cursor', { home, env })) {
    fs.rmSync(stableDirs(home).hooks, { recursive: true, force: true });
  }
  return { file };
}

function isInstalled({ home } = {}) {
  const config = readJson(hooksFile(home));
  return Object.values(config.hooks || {}).some((list) => Array.isArray(list) && list.some(isOurs));
}

module.exports = { available, install, uninstall, isInstalled, hooksFile, MARKER };
