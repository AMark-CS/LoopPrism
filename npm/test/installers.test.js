'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const codex = require('../lib/codex');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'lpa-'));
const readHooks = (home) => JSON.parse(fs.readFileSync(path.join(home, '.codex', 'hooks.json'), 'utf8')).hooks;
const ours = (hooks) =>
  Object.values(hooks).flat().flatMap((g) => g.hooks).filter((h) => h.command.includes(codex.MARKER));

test('codex install is idempotent and keeps other hooks', () => {
  const home = tmp();
  const file = path.join(home, '.codex', 'hooks.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const mine = { type: 'command', command: 'echo mine' };
  fs.writeFileSync(file, JSON.stringify({ description: 'keep', hooks: { Stop: [{ hooks: [mine] }] } }));

  codex.install({ home, env: {} });
  codex.install({ home, env: {} });
  const hooks = readHooks(home);
  assert.equal(ours(hooks).length, 5); // one per event, not duplicated by the second run
  assert.deepEqual(hooks.Stop[0].hooks, [mine]);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).description, 'keep');
  assert.ok(fs.existsSync(path.join(home, '.loopprism', 'hooks', 'hook.js')));
  assert.ok(fs.existsSync(path.join(home, '.loopprism', 'hooks', 'config.js')));
  assert.equal(codex.isInstalled({ home, env: {} }), true);

  codex.uninstall({ home, env: {} });
  const after = readHooks(home);
  assert.equal(ours(after).length, 0);
  assert.deepEqual(after.Stop[0].hooks, [mine]);
  assert.equal(Object.keys(after).join(), 'Stop');
  assert.equal(fs.existsSync(path.join(home, '.loopprism', 'hooks')), false);
});

test('codex install honours CODEX_HOME and refuses a broken hooks.json', () => {
  const home = tmp();
  const codexHome = path.join(tmp(), 'custom');
  codex.install({ home, env: { CODEX_HOME: codexHome } });
  assert.ok(fs.existsSync(path.join(codexHome, 'hooks.json')));

  const bad = path.join(tmp(), 'c');
  fs.mkdirSync(bad);
  fs.writeFileSync(path.join(bad, 'hooks.json'), '{ nope');
  assert.throws(() => codex.install({ home, env: { CODEX_HOME: bad } }), /Cannot parse/);
  assert.equal(fs.readFileSync(path.join(bad, 'hooks.json'), 'utf8'), '{ nope'); // left untouched
});

const claudeCli = spawnSync('claude', ['--version']).status === 0;

test('the plugin and both marketplaces pass `claude plugin validate`', { skip: !claudeCli && 'claude CLI not installed' }, () => {
  const env = { ...process.env, CLAUDE_CONFIG_DIR: tmp() };
  for (const target of ['plugin', '.', '../.claude-plugin/..']) {
    const r = spawnSync('claude', ['plugin', 'validate', path.join(__dirname, '..', target)], { env, encoding: 'utf8' });
    assert.equal(r.status, 0, `${target}: ${r.stdout}${r.stderr}`);
  }
});

test('claude install registers the plugin in an isolated config', { skip: !claudeCli && 'claude CLI not installed' }, () => {
  const claude = require('../lib/claude');
  const home = tmp();
  const env = { ...process.env, CLAUDE_CONFIG_DIR: path.join(home, 'claude-config'), HOME: home };
  claude.install({ home, env });
  assert.equal(claude.isInstalled(env), true);
  claude.uninstall({ home, env });
  assert.equal(claude.isInstalled(env), false);
  assert.equal(fs.existsSync(path.join(home, '.loopprism', 'claude-marketplace')), false);
});

const workbuddy = require('../lib/workbuddy');
const wbFile = (home) => path.join(home, '.workbuddy', 'settings.json');
const wbHooks = (home) => JSON.parse(fs.readFileSync(wbFile(home), 'utf8')).hooks;

test('workbuddy install merges into settings.json, is idempotent and keeps everything else', () => {
  const home = tmp();
  const file = wbFile(home);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const mine = { type: 'command', command: 'echo mine', timeout: 9 };
  const before = { sandbox: { extraAllowWrite: ['/x'] }, enabledPlugins: { a: true }, hooks: { Stop: [{ hooks: [mine] }] } };
  fs.writeFileSync(file, JSON.stringify(before));

  workbuddy.install({ home, env: {} });
  workbuddy.install({ home, env: {} });
  const after = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual(after.sandbox, before.sandbox);
  assert.deepEqual(after.enabledPlugins, before.enabledPlugins);
  const mineAndOurs = Object.values(after.hooks).flat().flatMap((g) => g.hooks);
  assert.equal(mineAndOurs.filter((h) => h.command.includes(workbuddy.MARKER)).length, 6); // not doubled by the 2nd run
  assert.deepEqual(after.hooks.Stop[0].hooks, [mine]);
  assert.match(after.hooks.PostToolUse[0].hooks[0].command, /--agent workbuddy$/);
  assert.equal(after.hooks.PostToolUse[0].matcher, '*');
  assert.equal(workbuddy.isInstalled({ home, env: {} }), true);
  assert.ok(fs.existsSync(`${file}.loopprism.bak`)); // the first copy of the user's file is kept
  assert.deepEqual(JSON.parse(fs.readFileSync(`${file}.loopprism.bak`, 'utf8')), before);

  workbuddy.uninstall({ home, env: {} });
  const gone = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual(gone, before);
  assert.equal(fs.existsSync(path.join(home, '.loopprism', 'hooks')), false);
});

test('workbuddy honours WORKBUDDY_CONFIG_DIR, detects the app by its folder and refuses a broken settings.json', () => {
  const home = tmp();
  assert.equal(workbuddy.available({ home, env: {} }), false);
  const dir = path.join(tmp(), 'wb');
  assert.equal(workbuddy.available({ home, env: { WORKBUDDY_CONFIG_DIR: dir } }), false);
  workbuddy.install({ home, env: { WORKBUDDY_CONFIG_DIR: dir } });
  assert.ok(fs.existsSync(path.join(dir, 'settings.json')));
  assert.equal(workbuddy.available({ home, env: { WORKBUDDY_CONFIG_DIR: dir } }), true);

  const bad = path.join(tmp(), 'b');
  fs.mkdirSync(bad);
  fs.writeFileSync(path.join(bad, 'settings.json'), '{ nope');
  assert.throws(() => workbuddy.install({ home, env: { WORKBUDDY_CONFIG_DIR: bad } }), /Cannot parse/);
  assert.equal(fs.readFileSync(path.join(bad, 'settings.json'), 'utf8'), '{ nope');
});

test('Codex and WorkBuddy share the hook scripts: removing one keeps them for the other', () => {
  const home = tmp();
  codex.install({ home, env: {} });
  workbuddy.install({ home, env: {} });
  const scripts = path.join(home, '.loopprism', 'hooks', 'hook.js');
  codex.uninstall({ home, env: {} });
  assert.ok(fs.existsSync(scripts), 'WorkBuddy still needs the scripts');
  workbuddy.uninstall({ home, env: {} });
  assert.equal(fs.existsSync(scripts), false);
});
