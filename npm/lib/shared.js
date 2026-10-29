'use strict';
// The hook scripts under ~/.loopprism/hooks are shared by Codex, WorkBuddy, DeepSeek Harness, Gemini CLI and Cursor:
// keep the copy while another of them still points at it.
const USERS = ['codex', 'workbuddy', 'dsh', 'gemini', 'cursor'];

function hooksInUse(except, opts) {
  return USERS.filter((n) => n !== except).some((n) => {
    try {
      return require(`./${n}`).isInstalled(opts);
    } catch {
      return false; // an unreadable config does not keep our copy alive
    }
  });
}

module.exports = { hooksInUse };
