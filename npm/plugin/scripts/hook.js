#!/usr/bin/env node
'use strict';
// LoopPrism hook for Claude Code and Codex.
//
// Reads one hook event as JSON on stdin and forwards it to the LoopPrism API.
// It must never get in the agent's way: it always prints `{}`, always exits 0,
// gives up after one second, and skips sending for a few seconds after a
// failure so a stopped server does not slow every tool call.
//
//   node hook.js --agent claude-code|codex
//
// Environment: LOOPPRISM_URL (default http://127.0.0.1:8080),
// LOOPPRISM_DISABLE=1, LOOPPRISM_NO_PROMPTS=1 (do not send prompt text),
// LOOPPRISM_DEBUG=1 (print problems to stderr).

const fs = require('fs');
const os = require('os');
const path = require('path');
const { baseUrl } = require('./config');
const { turnUsage } = require('./usage');

const EVENTS = {
  SessionStart: 'session_start',
  UserPromptSubmit: 'prompt',
  PostToolUse: 'tool',
  PostToolUseFailure: 'tool_failure',
  Stop: 'stop',
  SessionEnd: 'session_end',
};

// Claude Code feeds some automatic messages back as prompts (system reminders,
// background task notifications). They are not something the user typed, so
// their text is not sent.
const AUTOMATED_PROMPT = /^\s*<(system-reminder|task-notification|[a-z-]+-event)\b/;
const AUTOMATED_LABEL = '(automated message)';

const TIMEOUT_MS = 1000;
const BACKOFF_MS = 10_000;
const MAX_STRING = 4000;

function clip(value, depth = 0) {
  if (typeof value === 'string') {
    return value.length > MAX_STRING
      ? `${value.slice(0, MAX_STRING)}... [${value.length - MAX_STRING} more chars]`
      : value;
  }
  if (depth >= 6) return '...';
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => clip(v, depth + 1));
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value).slice(0, 50)) out[k] = clip(v, depth + 1);
    return out;
  }
  return value;
}

/** Map a hook payload to a LoopPrism ingest event, or null if it should be skipped. */
function buildEvent(input, agent, env = process.env) {
  const kind = EVENTS[input && input.hook_event_name];
  if (!kind || !input.session_id) return null;
  const event = {
    agent,
    event: kind,
    session_id: String(input.session_id),
    turn_id: input.turn_id,
    cwd: input.cwd,
    model: input.model,
  };
  if (kind === 'prompt' && !env.LOOPPRISM_NO_PROMPTS) {
    const prompt = typeof input.prompt === 'string' ? input.prompt : '';
    event.prompt = AUTOMATED_PROMPT.test(prompt) ? AUTOMATED_LABEL : clip(prompt);
  }
  if (kind === 'tool' || kind === 'tool_failure') {
    event.tool_name = input.tool_name;
    event.tool_input = clip(input.tool_input);
    event.tool_use_id = input.tool_use_id;
    event.duration_ms = input.duration_ms;
    if (kind === 'tool') event.tool_response = clip(input.tool_response);
    else event.error = clip(input.error);
  }
  return event;
}

function backoffFile() {
  return path.join(os.tmpdir(), 'loopprism-hook-backoff');
}

function inBackoff(now = Date.now()) {
  try {
    return now - fs.statSync(backoffFile()).mtimeMs < BACKOFF_MS;
  } catch {
    return false;
  }
}

function startBackoff() {
  try {
    fs.writeFileSync(backoffFile(), String(Date.now()));
  } catch {
    // best effort
  }
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

async function send(event, url = baseUrl()) {
  const res = await fetch(`${url}/api/ingest/events`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ events: [event] }),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`LoopPrism answered HTTP ${res.status}`);
}

async function main(argv = process.argv, env = process.env) {
  const i = argv.indexOf('--agent');
  const agent = i >= 0 && argv[i + 1] ? argv[i + 1] : 'unknown';
  try {
    if (env.LOOPPRISM_DISABLE === '1' || inBackoff()) return;
    const input = JSON.parse((await readStdin()) || '{}');
    const event = buildEvent(input, agent, env);
    if (!event) return;
    if (event.event === 'stop') {
      const usage = turnUsage(agent, input, env);
      if (usage.length) event.usage = usage;
    }
    try {
      await send(event);
    } catch (err) {
      startBackoff();
      throw err;
    }
  } catch (err) {
    if (env.LOOPPRISM_DEBUG === '1') process.stderr.write(`loopprism hook: ${err.message}\n`);
  } finally {
    process.stdout.write('{}');
  }
}

module.exports = { EVENTS, AUTOMATED_LABEL, buildEvent, clip, send };

if (require.main === module) main().then(() => process.exit(0));
