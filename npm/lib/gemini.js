'use strict';
// Gemini CLI: register LoopPrism's hook in the `hooks` key of ~/.gemini/settings.json, merged and
// idempotent, and keep a copy of the hook scripts under ~/.loopprism/hooks. Gemini CLI has the same
// matcher groups and a JSON event on stdin as Claude Code, but its own event names (BeforeAgent,
// AfterTool, AfterAgent, ...) and its timeouts are in milliseconds. The command uses an absolute path.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { packageRoot, stableDirs } = require('./paths');
const { atomicWrite, backupOnce } = require('./fsutil');

const MARKER = path.join('.loopprism', 'hooks', 'hook.js');
// BeforeAgent: the user's prompt; AfterTool: a tool finished (its result may carry an error);
// AfterAgent: the model's final answer of the turn.
const WANTED = [
  { event: 'SessionStart' },
  { event: 'BeforeAgent' },
  { event: 'AfterTool' },
  { event: 'AfterAgent' },
  { event: 'SessionEnd', timeout: 2000 },
];

const isOurs = (handler) =>
  typeof handler.command === 'string' && handler.command.includes(MARKER);

function geminiHome(env = process.env, home = os.homedir()) {
  return path.join(env.GEMINI_CLI_HOME || home, '.gemini');
}

function settingsFile(env = process.env, home) {
  return path.join(geminiHome(env, home), 'settings.json');
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return {};
    throw new Error(`Cannot parse ${file}: ${err.message}. Fix or remove it, then retry.`);
  }
}

/** Remove our handlers (and any groups/events left empty). Mutates and returns config. */
function stripOurs(config) {
  const hooks = config.hooks && typeof config.hooks === 'object' ? config.hooks : {};
  for (const [event, groups] of Object.entries(hooks)) {
    if (!Array.isArray(groups)) continue;
    hooks[event] = groups
      .map((g) => ({ ...g, hooks: (g.hooks || []).filter((h) => !isOurs(h)) }))
      .filter((g) => g.hooks.length > 0);
    if (hooks[event].length === 0) delete hooks[event];
  }
  if (Object.keys(hooks).length === 0) delete config.hooks;
  else config.hooks = hooks;
  return config;
}

function addOurs(config, hookJs) {
  const command = `node "${hookJs}" --agent gemini`;
  config.hooks = config.hooks || {};
  for (const w of WANTED) {
    const handler = { type: 'command', command, timeout: w.timeout || 5000 };
    const group = { hooks: [handler] };
    (config.hooks[w.event] ||= []).push(group);
  }
  return config;
}

/** Is Gemini CLI on this machine? Its home folder exists once it has been run. */
function available({ home, env = process.env } = {}) {
  return fs.existsSync(geminiHome(env, home));
}

function install({ home, env = process.env } = {}) {
  const dirs = stableDirs(home);
  fs.rmSync(dirs.hooks, { recursive: true, force: true });
  fs.cpSync(path.join(packageRoot, 'plugin', 'scripts'), dirs.hooks, { recursive: true });

  const file = settingsFile(env, home);
  const config = stripOurs(readJson(file));
  addOurs(config, path.join(dirs.hooks, 'hook.js'));
  backupOnce(file); // the user's own file: keep how it was before we first touched it
  atomicWrite(file, `${JSON.stringify(config, null, 2)}\n`);
  return { file, hookScript: path.join(dirs.hooks, 'hook.js') };
}

function uninstall({ home, env = process.env } = {}) {
  const file = settingsFile(env, home);
  if (fs.existsSync(file)) {
    atomicWrite(file, `${JSON.stringify(stripOurs(readJson(file)), null, 2)}\n`);
  }
  // The scripts are shared with the other apps' hooks: keep them while one still uses them.
  const shared = require('./shared').hooksInUse('gemini', { home, env });
  if (!shared) fs.rmSync(stableDirs(home).hooks, { recursive: true, force: true });
  return { file };
}

function isInstalled({ home, env = process.env } = {}) {
  const config = readJson(settingsFile(env, home));
  return Object.values(config.hooks || {}).some(
    (groups) => Array.isArray(groups) && groups.some((g) => (g.hooks || []).some(isOurs)),
  );
}

module.exports = { available, install, uninstall, isInstalled, stripOurs, addOurs, settingsFile, MARKER };
