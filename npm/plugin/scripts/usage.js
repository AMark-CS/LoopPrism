'use strict';
// Token usage of the turn that just ended, read from the agent's own session
// transcript, so LoopPrism can price it. Hook payloads carry no token counts.
//
//   Claude Code: ~/.claude/projects/<project>/<session>.jsonl, one `assistant`
//                line per content block, repeated per API response (dedupe by
//                message.id).
//   Codex:       ~/.codex/sessions/Y/M/D/rollout-*.jsonl, `token_usage_record`
//                lines per response, tagged with the turn they belong to.
//
//   WorkBuddy:   ~/.workbuddy/projects/<project>/<session>.jsonl, Responses-style items; the
//                usage of a model response (providerData.rawUsage) sits on one item of it, all
//                items of a response share providerData.messageId.
//
// Returns a list of { model, input_tokens (uncached), output_tokens,
// cache_read_tokens, cache_write_tokens, cache_write_1h_tokens, long_context,
// calls }. No dependencies: copied next to hook.js.
const fs = require('fs');
const os = require('os');
const path = require('path');

const MAX_READ_BYTES = 48 * 1024 * 1024;
const LONG_CONTEXT_TOKENS = 100_000;

function readLines(file) {
  const fd = fs.openSync(file, 'r');
  try {
    const size = fs.fstatSync(fd).size;
    const start = Math.max(0, size - MAX_READ_BYTES);
    const buf = Buffer.alloc(size - start);
    fs.readSync(fd, buf, 0, buf.length, start);
    const lines = buf.toString('utf8').split('\n');
    if (start > 0) lines.shift(); // first line is cut off
    const out = [];
    for (const line of lines) {
      if (!line) continue;
      try {
        out.push(JSON.parse(line));
      } catch {
        // partial or foreign line
      }
    }
    return out;
  } finally {
    fs.closeSync(fd);
  }
}

class Totals {
  constructor() {
    this.rows = new Map();
  }

  add(model, u) {
    if (!model || model === '<synthetic>') return;
    const key = `${model}|${u.long_context ? 1 : 0}`;
    let row = this.rows.get(key);
    if (!row) {
      row = {
        model,
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        cache_write_1h_tokens: 0,
        long_context: Boolean(u.long_context),
        calls: 0,
      };
      this.rows.set(key, row);
    }
    for (const k of [
      'input_tokens',
      'output_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'cache_write_1h_tokens',
    ]) {
      row[k] += u[k] || 0;
    }
    row.calls += 1;
  }

  list() {
    return [...this.rows.values()].filter(
      (r) => r.input_tokens || r.output_tokens || r.cache_read_tokens || r.cache_write_tokens || r.cache_write_1h_tokens,
    );
  }
}

const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);

// ---------------------------------------------------------------- Claude Code

/** A line the user typed (not a tool result or injected context). */
function isUserPrompt(entry) {
  if (entry.type !== 'user' || entry.isMeta || entry.isSidechain) return false;
  const content = entry.message && entry.message.content;
  if (typeof content === 'string') return true;
  return (
    Array.isArray(content) &&
    content.some((b) => b && b.type === 'text') &&
    !content.some((b) => b && b.type === 'tool_result')
  );
}

function claudeUsage(entries) {
  let start = 0;
  entries.forEach((e, i) => {
    if (isUserPrompt(e)) start = i + 1;
  });

  // A response is logged once per content block with the same message.id;
  // keep the largest value of each counter.
  const byId = new Map();
  for (const e of entries.slice(start)) {
    const m = e.type === 'assistant' && e.message;
    if (!m || !m.usage || !m.model) continue;
    const id = m.id || e.uuid;
    const u = m.usage;
    const cc = u.cache_creation || {};
    const cur = {
      model: m.model,
      input: num(u.input_tokens),
      output: num(u.output_tokens),
      read: num(u.cache_read_input_tokens),
      write5m: 'ephemeral_5m_input_tokens' in cc ? num(cc.ephemeral_5m_input_tokens) : num(u.cache_creation_input_tokens),
      write1h: num(cc.ephemeral_1h_input_tokens),
    };
    const prev = byId.get(id);
    if (prev) {
      for (const k of ['input', 'output', 'read', 'write5m', 'write1h']) prev[k] = Math.max(prev[k], cur[k]);
    } else {
      byId.set(id, cur);
    }
  }

  const totals = new Totals();
  for (const c of byId.values()) {
    totals.add(c.model, {
      input_tokens: c.input,
      output_tokens: c.output,
      cache_read_tokens: c.read,
      cache_write_tokens: c.write5m,
      cache_write_1h_tokens: c.write1h,
      long_context: c.input + c.read + c.write5m + c.write1h > LONG_CONTEXT_TOKENS,
    });
  }
  return totals.list();
}

// ---------------------------------------------------------------------- Codex

function codexUsage(entries, turnId) {
  const modelOf = new Map();
  for (const e of entries) {
    if (e.type === 'turn_context' && e.payload && e.payload.turn_id && e.payload.model) {
      modelOf.set(e.payload.turn_id, e.payload.model);
    }
  }
  const seen = new Set();
  const totals = new Totals();
  for (const e of entries) {
    const p = e.type === 'token_usage_record' && e.payload;
    if (!p || !p.usage) continue;
    // Sub-turns (reviews, sub-agents) carry the user's turn as root_turn_id.
    if (turnId && p.turn_id !== turnId && p.root_turn_id !== turnId) continue;
    const key = p.response_id || `${p.turn_id}:${e.ordinal}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const u = p.usage;
    // OpenAI counts cached tokens inside input_tokens.
    const cached = num(u.cached_input_tokens);
    const written = num(u.cache_write_input_tokens);
    totals.add(modelOf.get(p.turn_id), {
      input_tokens: Math.max(0, num(u.input_tokens) - cached - written),
      output_tokens: num(u.output_tokens),
      cache_read_tokens: cached,
      cache_write_tokens: written,
    });
  }
  return totals.list();
}

function findCodexRollout(sessionId, home = os.homedir(), env = process.env) {
  const root = path.join(env.CODEX_HOME || path.join(home, '.codex'), 'sessions');
  const sub = (dir) => {
    try {
      return fs.readdirSync(dir).sort().reverse();
    } catch {
      return [];
    }
  };
  let checked = 0;
  for (const y of sub(root)) {
    for (const m of sub(path.join(root, y))) {
      for (const d of sub(path.join(root, y, m))) {
        if (++checked > 120) return null;
        const dir = path.join(root, y, m, d);
        const hit = sub(dir).find((f) => f.startsWith('rollout-') && f.includes(sessionId));
        if (hit) return path.join(dir, hit);
      }
    }
  }
  return null;
}

// ------------------------------------------------------------------ WorkBuddy

/** A message the user typed (not an injected reminder or a compaction summary). */
function isWorkbuddyPrompt(entry) {
  if (entry.type !== 'message' || entry.role !== 'user') return false;
  const pd = entry.providerData || {};
  if (pd.isSummary || pd.isCompacted) return false;
  // The app prepends its context: <system-reminder ...>...</system-reminder><user_query>prompt</user_query>
  const text = (Array.isArray(entry.content) ? entry.content : [])
    .filter((p) => p && typeof p.text === 'string')
    .map((p) => p.text)
    .join('')
    .replace(/<system-reminder\b[^>]*>[\s\S]*?<\/system-reminder>/g, '');
  return text.trim() !== '';
}

function workbuddyUsage(entries) {
  let start = 0;
  entries.forEach((e, i) => {
    if (isWorkbuddyPrompt(e)) start = i + 1;
  });
  const byId = new Map();
  for (const e of entries.slice(start)) {
    const pd = e.providerData || {};
    const raw = pd.rawUsage;
    const alt = e.message && e.message.usage;
    if ((!raw && !alt) || !pd.messageId) continue;
    if (byId.has(pd.messageId)) continue; // usage of a response is written once; keep the first
    const r = raw || {};
    const a = alt || {};
    const details = r.prompt_tokens_details || {};
    const prompt = num(r.prompt_tokens) || num(a.input_tokens);
    const cached = Math.max(
      num(r.prompt_cache_hit_tokens),
      num(r.cache_read_input_tokens),
      num(r.cached_tokens),
      num(details.cached_tokens),
      num(a.cache_read_input_tokens),
    );
    const written = num(r.cache_creation_input_tokens) || num(r.prompt_cache_write_tokens);
    byId.set(pd.messageId, {
      model: pd.model || pd.requestModelId || pd.requestModelName,
      input: Math.max(0, prompt - cached - written), // prompt_tokens includes the cached part
      output: num(r.completion_tokens) || num(a.output_tokens),
      read: cached,
      write: written,
    });
  }
  const totals = new Totals();
  for (const c of byId.values()) {
    totals.add(c.model, {
      input_tokens: c.input,
      output_tokens: c.output,
      cache_read_tokens: c.read,
      cache_write_tokens: c.write,
    });
  }
  return totals.list();
}

/** Usage for the turn a Stop hook reports, or [] when it can't be determined. */
function turnUsage(agent, input, env = process.env) {
  try {
    if (agent === 'claude-code') {
      const file = input.transcript_path;
      return file && fs.existsSync(file) ? claudeUsage(readLines(file)) : [];
    }
    if (agent === 'workbuddy') {
      const file = input.transcript_path;
      return file && fs.existsSync(file) ? workbuddyUsage(readLines(file)) : [];
    }
    if (agent === 'codex') {
      const file =
        (input.transcript_path && fs.existsSync(input.transcript_path) && input.transcript_path) ||
        findCodexRollout(String(input.session_id), os.homedir(), env);
      return file ? codexUsage(readLines(file), input.turn_id) : [];
    }
  } catch {
    // never let pricing problems reach the agent
  }
  return [];
}

module.exports = { turnUsage, claudeUsage, codexUsage, workbuddyUsage, findCodexRollout, isUserPrompt };
