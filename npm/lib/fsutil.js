'use strict';
// Safe writes for files other programs also read (Codex's hooks.json, LoopPrism's own settings).
//
// A plain writeFileSync truncates first: a crash, a full disk or a concurrent reader can see (or
// leave behind) half a file. Writing a sibling temp file and renaming it over the target is
// all-or-nothing. On Windows the rename can fail while another process (an editor, antivirus,
// the agent itself) has the target open, so it is retried briefly.
const fs = require('fs');
const path = require('path');

const RETRYABLE = new Set(['EPERM', 'EBUSY', 'EACCES']);
let counter = 0;

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** Replace `file` with `data` atomically; the file mode is kept (or `mode` for a new file). */
function atomicWrite(file, data, { mode } = {}) {
  const dir = path.dirname(file);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = path.join(dir, `.${path.basename(file)}.tmp.${process.pid}.${Date.now()}.${counter++}`);
  let keep = mode;
  try {
    keep = fs.statSync(file).mode & 0o777;
  } catch {
    /* new file */
  }
  const fd = fs.openSync(tmp, 'w', keep ?? 0o666);
  try {
    fs.writeFileSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  try {
    for (let attempt = 0; ; attempt++) {
      try {
        fs.renameSync(tmp, file);
        return;
      } catch (err) {
        if (!RETRYABLE.has(err.code) || attempt >= 8) throw err;
        sleepSync(25 * (attempt + 1));
      }
    }
  } catch (err) {
    fs.rmSync(tmp, { force: true });
    throw err;
  }
}

/** Keep the first copy of a file we are about to change for the first time (`<file>.loopprism.bak`). */
function backupOnce(file, suffix = '.loopprism.bak') {
  const bak = `${file}${suffix}`;
  if (fs.existsSync(file) && !fs.existsSync(bak)) fs.copyFileSync(file, bak);
  return bak;
}

module.exports = { atomicWrite, backupOnce };
