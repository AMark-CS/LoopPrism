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
