'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { claudeUsage, codexUsage, turnUsage, findCodexRollout } = require('../plugin/scripts/usage');

const asst = (id, model, usage, extra = {}) => ({ type: 'assistant', uuid: `u-${id}-${Math.random()}`, message: { id, model, usage }, ...extra });
const user = (content, extra = {}) => ({ type: 'user', message: { role: 'user', content }, ...extra });

test('claude: counts only the current turn and dedupes repeated responses', () => {
  const entries = [
    user('old prompt'),
    asst('m0', 'claude-opus-5-5', { input_tokens: 999, output_tokens: 999 }),
    user('fix the bug'),
    // one response logged once per content block, output growing as it streams
    asst('m1', 'claude-sonnet-5-5', { input_tokens: 10, output_tokens: 5, cache_read_input_tokens: 100, cache_creation: { ephemeral_5m_input_tokens: 7, ephemeral_1h_input_tokens: 3 } }),
    asst('m1', 'claude-sonnet-5-5', { input_tokens: 10, output_tokens: 40, cache_read_input_tokens: 100, cache_creation: { ephemeral_5m_input_tokens: 7, ephemeral_1h_input_tokens: 3 } }),
    user([{ type: 'tool_result', tool_use_id: 't', content: 'ok' }]), // not a new prompt
    asst('m2', 'claude-sonnet-5-5', { input_tokens: 1, output_tokens: 2 }),
    asst('m3', '<synthetic>', { input_tokens: 5, output_tokens: 5 }),
  ];
  const [row, ...rest] = claudeUsage(entries);
  assert.equal(rest.length, 0);
  assert.deepEqual(
    { ...row },
    { model: 'claude-sonnet-5-5', input_tokens: 11, output_tokens: 42, cache_read_tokens: 100, cache_write_tokens: 7, cache_write_1h_tokens: 3, long_context: false, calls: 2 },
  );
});

test('claude: flags long-context responses and keeps them separate', () => {
  const [short, long] = claudeUsage([
    user('go'),
    asst('a', 'claude-haiku-5-5', { input_tokens: 10, output_tokens: 1 }),
    asst('b', 'claude-haiku-5-5', { input_tokens: 150000, output_tokens: 1 }),
  ]);
  assert.equal(short.long_context, false);
  assert.equal(long.long_context, true);
});

test('codex: sums the turn (and its sub-turns), splits cached input out of input', () => {
  const rec = (turn, root, resp, usage) => ({ type: 'token_usage_record', ordinal: Math.random(), payload: { turn_id: turn, root_turn_id: root, response_id: resp, usage } });
  const entries = [
    { type: 'turn_context', payload: { turn_id: 'T1', model: 'gpt-6.1-sol' } },
    { type: 'turn_context', payload: { turn_id: 'T2', model: 'gpt-6-luna' } },
    rec('T1', 'T1', 'r1', { input_tokens: 1000, cached_input_tokens: 600, output_tokens: 50 }),
    rec('T1', 'T1', 'r1', { input_tokens: 1000, cached_input_tokens: 600, output_tokens: 50 }), // duplicate
    rec('T2', 'T1', 'r2', { input_tokens: 200, cached_input_tokens: 0, output_tokens: 10 }), // sub-agent
    rec('T9', 'T9', 'r9', { input_tokens: 5000, output_tokens: 5000 }), // other turn
  ];
  const rows = codexUsage(entries, 'T1');
  const sol = rows.find((r) => r.model === 'gpt-6.1-sol');
  assert.deepEqual([sol.input_tokens, sol.cache_read_tokens, sol.output_tokens], [400, 600, 50]);
  assert.equal(rows.find((r) => r.model === 'gpt-6-luna').input_tokens, 200);
  assert.equal(rows.length, 2);
});

test('turnUsage reads the transcript file and never throws', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lp-usage-'));
  const file = path.join(dir, 's.jsonl');
  fs.writeFileSync(file, [user('hi'), asst('m1', 'claude-opus-5', { input_tokens: 3, output_tokens: 4 })].map((e) => JSON.stringify(e)).join('\n') + '\n{broken');
  assert.equal(turnUsage('claude-code', { transcript_path: file })[0].output_tokens, 4);
  assert.deepEqual(turnUsage('claude-code', { transcript_path: path.join(dir, 'missing') }), []);
  assert.deepEqual(turnUsage('someone-else', {}), []);
});

test('codex: finds the rollout file by session id', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'lp-codex-'));
  const day = path.join(home, '.codex', 'sessions', '2026', '10', '28');
  fs.mkdirSync(day, { recursive: true });
  fs.writeFileSync(path.join(day, 'rollout-2026-10-28T10-00-00-abc123.jsonl'), '');
  assert.equal(path.basename(findCodexRollout('abc123', home, {})), 'rollout-2026-10-28T10-00-00-abc123.jsonl');
  assert.equal(findCodexRollout('nope', home, {}), null);
});
