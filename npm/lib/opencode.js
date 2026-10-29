'use strict';
// OpenCode: install LoopPrism's plugin by copying one file into OpenCode's global plugin folder
// (~/.config/opencode/plugins, or $OPENCODE_CONFIG_DIR/plugins). OpenCode loads every file there at
// startup. The file starts with a marker comment, and only a file carrying it is ever replaced or
// removed, so a plugin of the user's own with the same name is left alone.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { packageRoot } = require('./paths');
const { atomicWrite } = require('./fsutil');

const MARKER = 'loopprism-opencode-plugin';
const FILE = 'loopprism.js';

function configDir(env = process.env, home = os.homedir()) {
  if (env.OPENCODE_CONFIG_DIR) return env.OPENCODE_CONFIG_DIR;
  return path.join(env.XDG_CONFIG_HOME || path.join(home, '.config'), 'opencode');
}

const pluginFile = (env, home) => path.join(configDir(env, home), 'plugins', FILE);
const source = () => path.join(packageRoot, 'plugin', 'opencode', FILE);
const isOurs = (file) => {
  try {
    return fs.readFileSync(file, 'utf8').slice(0, 200).includes(MARKER);
  } catch {
    return false;
  }
};

/** Is OpenCode on this machine? Its config or data folder exists once it has been run. */
function available({ home = os.homedir(), env = process.env } = {}) {
  return (
    fs.existsSync(configDir(env, home)) ||
    fs.existsSync(path.join(env.XDG_DATA_HOME || path.join(home, '.local', 'share'), 'opencode'))
  );
}

function install({ home = os.homedir(), env = process.env } = {}) {
  const file = pluginFile(env, home);
  if (fs.existsSync(file) && !isOurs(file)) {
    throw new Error(`${file} exists and is not LoopPrism's. Rename or remove it, then retry.`);
  }
  atomicWrite(file, fs.readFileSync(source(), 'utf8'));
  return { file };
}

function uninstall({ home = os.homedir(), env = process.env } = {}) {
  const file = pluginFile(env, home);
  if (isOurs(file)) fs.rmSync(file, { force: true });
  return { file };
}

function isInstalled({ home = os.homedir(), env = process.env } = {}) {
  return isOurs(pluginFile(env, home));
}

module.exports = { available, install, uninstall, isInstalled, pluginFile, configDir, MARKER };
