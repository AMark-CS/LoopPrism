'use strict';
// WorkBuddy (Tencent's desktop agent, a CodeBuddy product): register LoopPrism's hook in the
// `hooks` key of its user settings file, merged and idempotent, and keep a copy of the hook
// scripts under ~/.loopprism/hooks. WorkBuddy speaks Claude Code's hook protocol: the same
// matcher groups and events, a JSON event on stdin. It has no ${PLUGIN_ROOT} substitution for
// settings files, so the command uses an absolute path.
const fs = require('fs');
const path = require('path');
const { packageRoot, stableDirs, workbuddyHome } = require('./paths');
const { atomicWrite, backupOnce } = require('./fsutil');

const MARKER = path.join('.loopprism', 'hooks', 'hook.js');
// WorkBuddy's CLI sends Claude Code's events with the same payloads (hook_event_name, session_id,
// transcript_path, cwd, plus prompt / tool_name / tool_input / tool_response).
const WANTED = [
  { event: 'SessionStart' },
  { event: 'UserPromptSubmit' },
  { event: 'PostToolUse', matcher: '*' },
  { event: 'PostToolUseFailure', matcher: '*' },
  { event: 'Stop' },
  { event: 'SessionEnd', timeout: 2 },
];

const isOurs = (handler) =>
  typeof handler.command === 'string' && handler.command.includes(MARKER);

function settingsFile(env = process.env, home) {
  return path.join(workbuddyHome(env, home), 'settings.json');
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
  const command = `node "${hookJs}" --agent workbuddy`;
  config.hooks = config.hooks || {};
  for (const w of WANTED) {
    const handler = { type: 'command', command, timeout: w.timeout || 5 };
    const group = { hooks: [handler] };
    if (w.matcher) group.matcher = w.matcher;
    (config.hooks[w.event] ||= []).push(group);
  }
  return config;
}

/** Is WorkBuddy on this machine? Its home folder exists once it has been run. */
function available({ home, env = process.env } = {}) {
  return fs.existsSync(workbuddyHome(env, home));
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
  const shared = require('./shared').hooksInUse('workbuddy', { home, env });
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
