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

test('dsh writes a hooks file the bridge can run, and uninstall keeps scripts another app uses', () => {
  const dsh = require('../lib/dsh');
  const codex = require('../lib/codex');
  const { spawnSync } = require('node:child_process');
  const home = tmp();
  const env = {};
  assert.equal(dsh.isInstalled({ home }), false);
  const { file } = dsh.install({ home, env });
  assert.equal(dsh.isInstalled({ home }), true);
  const hooks = JSON.parse(fs.readFileSync(file, 'utf8')).hooks;
  assert.deepEqual(Object.keys(hooks), ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop']);
  const command = hooks.UserPromptSubmit[0].hooks[0].command;
  assert.match(command, /--agent dsh$/);

  // The command runs with a DeepSeek Harness payload on stdin and prints {}.
  const r = spawnSync(command, { shell: true, input: JSON.stringify({ hook_event_name: 'UserPromptSubmit', session_id: 's', prompt: 'x' }), encoding: 'utf8', env: { ...process.env, LOOPPRISM_DISABLE: '1' } });
  assert.equal(r.stdout, '{}');

  codex.install({ home, env });
  dsh.uninstall({ home, env });
  assert.equal(fs.existsSync(file), false);
  assert.ok(fs.existsSync(path.join(home, '.loopprism', 'hooks', 'hook.js'))); // Codex still uses it
  codex.uninstall({ home, env });
  assert.equal(fs.existsSync(path.join(home, '.loopprism', 'hooks')), false);
});

test('gemini: hooks go into ~/.gemini/settings.json in its own event names and milliseconds, idempotently', () => {
  const gemini = require('../lib/gemini');
  const home = tmp();
  const file = path.join(home, '.gemini', 'settings.json');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const mine = { type: 'command', command: 'echo mine' };
  fs.writeFileSync(file, JSON.stringify({ ui: { theme: 'x' }, hooks: { AfterAgent: [{ hooks: [mine] }] } }));
  gemini.install({ home, env: {} });
  gemini.install({ home, env: {} });
  const cfg = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(cfg.ui.theme, 'x');
  assert.deepEqual(Object.keys(cfg.hooks).sort(), ['AfterAgent', 'AfterTool', 'BeforeAgent', 'SessionEnd', 'SessionStart']);
  assert.equal(cfg.hooks.AfterAgent.length, 2); // ours, once, next to the user's
  assert.deepEqual(cfg.hooks.AfterAgent[0].hooks, [mine]);
  const ours = cfg.hooks.AfterTool[0].hooks[0];
  assert.match(ours.command, /--agent gemini$/);
  assert.equal(ours.timeout, 5000);
  assert.equal(gemini.isInstalled({ home, env: {} }), true);
  gemini.uninstall({ home, env: {} });
  const after = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual(Object.keys(after.hooks), ['AfterAgent']);
  assert.deepEqual(after.hooks.AfterAgent[0].hooks, [mine]);
});

test('hook.js understands Gemini CLI events, including a tool that failed', () => {
  const { buildEvent } = require('../plugin/scripts/hook');
  const base = { session_id: 's', cwd: '/w' };
  assert.equal(buildEvent({ ...base, hook_event_name: 'BeforeAgent', prompt: 'hi' }, 'gemini').event, 'prompt');
  const ok = buildEvent({ ...base, hook_event_name: 'AfterTool', tool_name: 'read_file', tool_input: { a: 1 }, tool_response: { llmContent: 'x' } }, 'gemini');
  assert.equal(ok.event, 'tool');
  const bad = buildEvent({ ...base, hook_event_name: 'AfterTool', tool_name: 'read_file', tool_input: {}, tool_response: { error: { message: 'nope' } } }, 'gemini');
  assert.equal(bad.event, 'tool_failure');
  assert.equal(bad.error, 'nope');
  assert.equal(buildEvent({ ...base, hook_event_name: 'AfterAgent' }, 'gemini').event, 'stop');
});
