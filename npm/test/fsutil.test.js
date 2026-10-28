'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { atomicWrite, backupOnce } = require('../lib/fsutil');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'lp-fs-'));

test('atomicWrite creates folders, replaces the file and leaves no temp file behind', () => {
  const dir = tmp();
  const file = path.join(dir, 'a', 'b', 'hooks.json');
  atomicWrite(file, 'one');
  atomicWrite(file, 'two');
  assert.equal(fs.readFileSync(file, 'utf8'), 'two');
  assert.deepEqual(fs.readdirSync(path.dirname(file)), ['hooks.json']);
});

test('atomicWrite keeps the mode of an existing file', { skip: process.platform === 'win32' && 'POSIX modes' }, () => {
  const file = path.join(tmp(), 'secret.json');
  fs.writeFileSync(file, 'x', { mode: 0o600 });
  atomicWrite(file, 'y');
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
});

test('a failed write leaves the old file intact and cleans up its temp file', () => {
  const dir = tmp();
  const target = path.join(dir, 'target');
  fs.mkdirSync(target); // renaming a file over a directory fails on every platform
  assert.throws(() => atomicWrite(target, 'data'));
  assert.deepEqual(fs.readdirSync(dir), ['target']);
});

test('backupOnce keeps only the first copy', () => {
  const file = path.join(tmp(), 'hooks.json');
  fs.writeFileSync(file, 'original');
  const bak = backupOnce(file);
  fs.writeFileSync(file, 'changed');
  backupOnce(file);
  assert.equal(fs.readFileSync(bak, 'utf8'), 'original');
  assert.equal(backupOnce(path.join(tmp(), 'missing.json')).endsWith('.loopprism.bak'), true); // no file, no copy, no error
});

test('the desktop app bundles the same helper', () => {
  const copy = path.join(__dirname, '..', '..', 'desktop', 'src', 'fsutil.js');
  assert.equal(fs.readFileSync(copy, 'utf8'), fs.readFileSync(path.join(__dirname, '..', 'lib', 'fsutil.js'), 'utf8'));
});
