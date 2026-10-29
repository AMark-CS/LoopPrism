'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const viewer = require('../plugin/scripts/viewer');
const { baseUrl } = require('../plugin/scripts/config');

function serve(handler) {
  const server = http.createServer(handler);
  return new Promise((r) => server.listen(0, '127.0.0.1', () => r({ server, url: `http://127.0.0.1:${server.address().port}` })));
}

test('status lists runs', async () => {
  const { server, url } = await serve((req, res) => {
    res.setHeader('content-type', 'application/json');
    if (req.url === '/api/health') return res.end('{"status":"ok"}');
    res.end(JSON.stringify({ traces: [{ timestamp: '2026-10-28 12:00:00', status: 'succeeded', tags: '{"agent":"codex"}', span_count: 4, error_count: 1, root_span_name: 'Fix tests' }] }));
  });
  const lines = [];
  const code = await viewer.status((l) => lines.push(l), url);
  server.close();
  assert.equal(code, 0);
  const text = lines.join('\n');
  assert.match(text, /is up/);
  assert.match(text, /succeeded\s+codex\s+4 spans\s+1 err\s+Fix tests/);
});

test('status explains how to start LoopPrism when it is down', async () => {
  const lines = [];
  const code = await viewer.status((l) => lines.push(l), 'http://127.0.0.1:1');
  assert.equal(code, 1);
  assert.match(lines.join('\n'), /not running[\s\S]*lprism proxy/);
});

test('baseUrl prefers env, then the default', () => {
  assert.equal(baseUrl({ LOOPPRISM_URL: 'http://h:9/' }, '/nonexistent'), 'http://h:9');
  assert.equal(baseUrl({}, '/nonexistent'), 'http://127.0.0.1:8080');
});

test('windowsInstallDirs reads the folders the installer recorded', () => {
  const { windowsInstallDirs } = require('../plugin/scripts/viewer');
  const out = [
    '',
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{abc}',
    '    InstallLocation    REG_SZ    D:\\Tools\\Loop Prism',
    '',
    'HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Other',
    '    InstallLocation    REG_SZ    C:\\Other',
    '',
  ].join('\r\n');
  const seen = [];
  const run = (cmd, args) => {
    seen.push([cmd, args[1].split('\\')[0]]);
    return { stdout: args[1].startsWith('HKCU') ? out : '' };
  };
  assert.deepEqual(windowsInstallDirs(run), ['D:\\Tools\\Loop Prism', 'C:\\Other']);
  assert.deepEqual(seen, [['reg', 'HKCU'], ['reg', 'HKLM']]);
});

test('desktopApp finds a Windows install in a folder the user chose', () => {
  const { desktopApp } = require('../plugin/scripts/viewer');
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lp-app-'));
  fs.writeFileSync(path.join(dir, 'LoopPrism.exe'), '');
  const real = Object.getOwnPropertyDescriptor(process, 'platform');
  Object.defineProperty(process, 'platform', { value: 'win32' });
  try {
    assert.equal(desktopApp({ LOCALAPPDATA: path.join(dir, 'none') }, () => ['C:\\unrelated', dir]), path.join(dir, 'LoopPrism.exe'));
    assert.equal(desktopApp({ LOCALAPPDATA: path.join(dir, 'none') }, () => { throw new Error('no reg'); }), null);
  } finally {
    Object.defineProperty(process, 'platform', real);
  }
});
