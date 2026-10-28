'use strict';
// Claude Code: copy the plugin to a stable folder, register it as a local
// marketplace and install it through the `claude plugin` commands.
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { packageRoot, stableDirs } = require('./paths');

const PLUGIN = 'loopprism@loopprism';

function run(args, env = process.env) {
  const r = spawnSync('claude', args, { encoding: 'utf8', env });
  return { ok: r.status === 0, out: `${r.stdout || ''}${r.stderr || ''}`.trim(), missing: r.error?.code === 'ENOENT' };
}

function available(env = process.env) {
  return !run(['--version'], env).missing;
}

function install({ home, env = process.env } = {}) {
  const dir = stableDirs(home).marketplace;
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  fs.cpSync(path.join(packageRoot, '.claude-plugin'), path.join(dir, '.claude-plugin'), { recursive: true });
  fs.cpSync(path.join(packageRoot, 'plugin'), path.join(dir, 'plugin'), { recursive: true });

  // Re-adding replaces a stale registration; removing first keeps it idempotent.
  run(['plugin', 'uninstall', PLUGIN], env);
  run(['plugin', 'marketplace', 'remove', 'loopprism'], env);
  const add = run(['plugin', 'marketplace', 'add', dir], env);
  if (!add.ok) throw new Error(`claude plugin marketplace add failed:\n${add.out}`);
  const inst = run(['plugin', 'install', PLUGIN], env);
  if (!inst.ok) throw new Error(`claude plugin install failed:\n${inst.out}`);
  return { marketplace: dir };
}

function uninstall({ home, env = process.env } = {}) {
  const a = run(['plugin', 'uninstall', PLUGIN], env);
  run(['plugin', 'marketplace', 'remove', 'loopprism'], env);
  fs.rmSync(stableDirs(home).marketplace, { recursive: true, force: true });
  return { ok: a.ok };
}

function isInstalled(env = process.env) {
  const r = run(['plugin', 'list'], env);
  return r.ok && /loopprism/.test(r.out);
}

module.exports = { available, install, uninstall, isInstalled, PLUGIN };
