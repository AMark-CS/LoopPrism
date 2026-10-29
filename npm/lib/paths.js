'use strict';
const os = require('os');
const path = require('path');

const packageRoot = path.resolve(__dirname, '..');

/** Stable copies live under ~/.loopprism so they survive an npx cache clean. */
function stableDirs(home = os.homedir()) {
  const base = path.join(home, '.loopprism');
  return {
    base,
    marketplace: path.join(base, 'claude-marketplace'),
    hooks: path.join(base, 'hooks'),
  };
}

function codexHome(env = process.env, home = os.homedir()) {
  return env.CODEX_HOME || path.join(home, '.codex');
}

/** WorkBuddy's data folder (WORKBUDDY_CONFIG_DIR overrides it). */
function workbuddyHome(env = process.env, home = os.homedir()) {
  return env.WORKBUDDY_CONFIG_DIR || path.join(home, '.workbuddy');
}

module.exports = { packageRoot, stableDirs, codexHome, workbuddyHome };
