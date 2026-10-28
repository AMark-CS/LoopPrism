'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { spawn } = require('node:child_process');
const path = require('node:path');
const { buildEvent, clip } = require('../plugin/scripts/hook');

const HOOK = path.join(__dirname, '..', 'plugin', 'scripts', 'hook.js');

test('maps hook events to ingest events', () => {
  const base = { session_id: 's1', cwd: '/p', hook_event_name: '' };
  const prompt = buildEvent({ ...base, hook_event_name: 'UserPromptSubmit', prompt: 'hi' }, 'claude-code', {});
  assert.deepEqual([prompt.event, prompt.prompt, prompt.agent, prompt.session_id], ['prompt', 'hi', 'claude-code', 's1']);

  const tool = buildEvent(
    { ...base, hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_input: { command: 'ls' }, tool_response: { out: 'x' }, tool_use_id: 't', duration_ms: 12 },
    'codex', {},
  );
  assert.equal(tool.event, 'tool');
  assert.equal(tool.tool_use_id, 't');
  assert.equal(tool.duration_ms, 12);
  assert.deepEqual(tool.tool_response, { out: 'x' });

  const failure = buildEvent({ ...base, hook_event_name: 'PostToolUseFailure', tool_name: 'Edit', error: 'nope' }, 'claude-code', {});
  assert.deepEqual([failure.event, failure.error, failure.tool_response], ['tool_failure', 'nope', undefined]);

  assert.equal(buildEvent({ ...base, hook_event_name: 'Stop' }, 'x', {}).event, 'stop');
  assert.equal(buildEvent({ ...base, hook_event_name: 'SessionEnd' }, 'x', {}).event, 'session_end');
});

test('skips unknown events and payloads without a session', () => {
  assert.equal(buildEvent({ session_id: 's', hook_event_name: 'Notification' }, 'x', {}), null);
  assert.equal(buildEvent({ hook_event_name: 'Stop' }, 'x', {}), null);
  assert.equal(buildEvent(null, 'x', {}), null);
});

test('LOOPPRISM_NO_PROMPTS keeps prompt text out', () => {
  const e = buildEvent({ session_id: 's', hook_event_name: 'UserPromptSubmit', prompt: 'secret' }, 'x', { LOOPPRISM_NO_PROMPTS: '1' });
  assert.equal(e.prompt, undefined);
});

test('clip caps long strings and deep nesting', () => {
  assert.match(clip('x'.repeat(10_000)), /more chars\]$/);
  assert.ok(clip('x'.repeat(10_000)).length < 4100);
  assert.equal(clip({ a: { b: { c: { d: { e: { f: { g: 1 } } } } } } }).a.b.c.d.e.f, '...');
});

function runHook(payload, env, args = ['--agent', 'claude-code']) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [HOOK, ...args], { env: { ...process.env, ...env } });
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (d) => (stdout += d));
    child.stderr.on('data', (d) => (stderr += d));
    const started = Date.now();
    child.on('close', (code) => resolve({ code, stdout, stderr, ms: Date.now() - started }));
    child.stdin.end(typeof payload === 'string' ? payload : JSON.stringify(payload));
  });
}

function fakeServer(status = 200) {
  const received = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (d) => (body += d));
    req.on('end', () => {
      received.push({ url: req.url, method: req.method, body: JSON.parse(body) });
      res.statusCode = status;
      res.end('{}');
    });
  });
  return new Promise((resolve) =>
    server.listen(0, '127.0.0.1', () => resolve({ server, received, url: `http://127.0.0.1:${server.address().port}` })),
  );
}

// each run gets its own tmp dir so the failure back-off file never leaks between tests
const isolated = (extra = {}) => {
  const dir = require('node:fs').mkdtempSync(path.join(require('node:os').tmpdir(), 'lp-'));
  return { TMPDIR: dir, TEMP: dir, TMP: dir, ...extra }; // os.tmpdir() reads TEMP/TMP on Windows
};

test('posts the event, prints {} and exits 0', async () => {
  const { server, received, url } = await fakeServer();
  const r = await runHook(
    { session_id: 's1', hook_event_name: 'PostToolUse', tool_name: 'Bash', tool_use_id: 't1' },
    isolated({ LOOPPRISM_URL: url }),
  );
  server.close();
  assert.deepEqual([r.code, r.stdout], [0, '{}']);
  assert.equal(received.length, 1);
  assert.equal(received[0].url, '/api/ingest/events');
  assert.equal(received[0].body.events[0].tool_name, 'Bash');
  assert.equal(received[0].body.events[0].agent, 'claude-code');
});

test('never fails when LoopPrism is down, and backs off afterwards', async () => {
  const env = isolated({ LOOPPRISM_URL: 'http://127.0.0.1:1', LOOPPRISM_DEBUG: '1' });
  const payload = { session_id: 's', hook_event_name: 'Stop' };
  const first = await runHook(payload, env);
  assert.deepEqual([first.code, first.stdout], [0, '{}']);
  assert.match(first.stderr, /loopprism hook:/);
  const second = await runHook(payload, env);
  assert.deepEqual([second.code, second.stdout, second.stderr], [0, '{}', '']);
});

test('survives a server error, garbage input, and being disabled', async () => {
  const { server, received, url } = await fakeServer(500);
  const bad = await runHook({ session_id: 's', hook_event_name: 'Stop' }, isolated({ LOOPPRISM_URL: url }));
  assert.deepEqual([bad.code, bad.stdout], [0, '{}']);
  const junk = await runHook('not json', isolated({ LOOPPRISM_URL: url }));
  assert.deepEqual([junk.code, junk.stdout], [0, '{}']);
  const off = await runHook({ session_id: 's', hook_event_name: 'Stop' }, isolated({ LOOPPRISM_URL: url, LOOPPRISM_DISABLE: '1' }));
  assert.equal(off.stdout, '{}');
  server.close();
  assert.equal(received.length, 1); // only the first request reached the server
});

test('injected notifications are not sent as if the user typed them', () => {
  const { AUTOMATED_LABEL } = require('../plugin/scripts/hook');
  for (const prompt of [
    '<system-reminder>\nThe session finished.</system-reminder>',
    '  <task-notification><task-id>x</task-id></task-notification>',
    '<side-sessions-event>None are working</side-sessions-event>',
  ]) {
    const e = buildEvent({ session_id: 's', hook_event_name: 'UserPromptSubmit', prompt }, 'claude-code', {});
    assert.equal(e.prompt, AUTOMATED_LABEL);
  }
  const real = buildEvent({ session_id: 's', hook_event_name: 'UserPromptSubmit', prompt: 'use <b> tags in the html' }, 'x', {});
  assert.equal(real.prompt, 'use <b> tags in the html');
});
