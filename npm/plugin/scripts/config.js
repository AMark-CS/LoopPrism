'use strict';
// Shared by the hook and the viewer. No dependencies: this folder is copied
// into the Claude Code plugin cache and into ~/.loopprism/hooks for Codex.
const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULT_URL = 'http://127.0.0.1:8080';

function configPath(home = os.homedir()) {
  return path.join(home, '.loopprism', 'agent.json');
}

/** Where the LoopPrism API listens: env var, then ~/.loopprism/agent.json, then the default. */
function baseUrl(env = process.env, home = os.homedir()) {
  if (env.LOOPPRISM_URL) return env.LOOPPRISM_URL.replace(/\/+$/, '');
  try {
    const url = JSON.parse(fs.readFileSync(configPath(home), 'utf8')).url;
    if (typeof url === 'string' && url) return url.replace(/\/+$/, '');
  } catch {
    // no config file: fall through
  }
  return DEFAULT_URL;
}

module.exports = { DEFAULT_URL, baseUrl, configPath };
