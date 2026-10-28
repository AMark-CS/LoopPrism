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

module.exports = { packageRoot, stableDirs, codexHome };
