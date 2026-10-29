'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const opencode = require('../lib/opencode');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'lpa-oc-'));

test('opencode install is idempotent, keeps a plugin of the user, and uninstall removes only ours', () => {
  const home = tmp();
  const env = {};
  const file = opencode.pluginFile(env, home);
  assert.equal(opencode.isInstalled({ home, env }), false);
  opencode.install({ home, env });
  opencode.install({ home, env });
  assert.equal(opencode.isInstalled({ home, env }), true);
  assert.ok(fs.readFileSync(file, 'utf8').includes(opencode.MARKER));
  opencode.uninstall({ home, env });
  assert.equal(fs.existsSync(file), false);

  fs.writeFileSync(file, '// my own plugin\n');
  assert.throws(() => opencode.install({ home, env }), /not LoopPrism's/);
  opencode.uninstall({ home, env });
  assert.equal(fs.readFileSync(file, 'utf8'), '// my own plugin\n'); // left alone
});

test('opencode honours OPENCODE_CONFIG_DIR', () => {
  const dir = path.join(tmp(), 'custom');
  opencode.install({ home: tmp(), env: { OPENCODE_CONFIG_DIR: dir } });
  assert.ok(fs.existsSync(path.join(dir, 'plugins', 'loopprism.js')));
});

test('the plugin turns OpenCode hooks into LoopPrism events', async () => {
  const got = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      got.push(...JSON.parse(body).events);
      res.end('{}');
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  process.env.LOOPPRISM_URL = `http://127.0.0.1:${server.address().port}`;
  try {
    const mod = await import(pathToFileURL(path.join(__dirname, '..', 'plugin', 'opencode', 'loopprism.js')).href);
    const hooks = await mod.LoopPrismPlugin({ directory: '/work/app' });
    await hooks['chat.message'](
      { sessionID: 's1', model: { providerID: 'p', modelID: 'm1' } },
      { parts: [{ type: 'text', text: 'fix the bug' }, { type: 'text', text: 'hidden', synthetic: true }] },
    );
    await hooks['tool.execute.before']({ tool: 'bash', sessionID: 's1', callID: 'c1' }, { args: {} });
    await hooks['tool.execute.after']({ tool: 'bash', sessionID: 's1', callID: 'c1', args: { command: 'ls' } }, { output: 'a\nb' });
    await hooks.event({ event: { type: 'session.idle', properties: { sessionID: 's1' } } });
    await hooks.event({ event: { type: 'session.idle', properties: { sessionID: 's1' } } }); // no second stop
  } finally {
    delete process.env.LOOPPRISM_URL;
    server.close();
  }
  assert.deepEqual(
    got.map((e) => [e.agent, e.event, e.session_id]),
    [['opencode', 'prompt', 's1'], ['opencode', 'tool', 's1'], ['opencode', 'stop', 's1']],
  );
  assert.equal(got[0].prompt, 'fix the bug');
  assert.equal(got[0].model, 'm1');
  assert.equal(got[0].cwd, '/work/app');
  assert.equal(got[1].tool_name, 'bash');
  assert.deepEqual(got[1].tool_input, { command: 'ls' });
  assert.equal(got[1].tool_response, 'a\nb');
  assert.ok(got[1].duration_ms >= 0);
});

test('the plugin stays quiet and never throws when LoopPrism is not running', async () => {
  process.env.LOOPPRISM_URL = 'http://127.0.0.1:9';
  try {
    const mod = await import(pathToFileURL(path.join(__dirname, '..', 'plugin', 'opencode', 'loopprism.js')).href + '?down');
    const hooks = await mod.LoopPrismPlugin({ directory: '/x' });
    await hooks['chat.message']({ sessionID: 's' }, { parts: [] });
    await hooks['tool.execute.after']({ tool: 't', sessionID: 's', callID: 'c', args: {} }, { output: '' });
  } finally {
    delete process.env.LOOPPRISM_URL;
  }
});
