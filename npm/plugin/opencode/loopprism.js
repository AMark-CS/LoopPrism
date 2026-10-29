// loopprism-opencode-plugin
// LoopPrism plugin for OpenCode: reports prompts, tool calls and the end of each turn to the local
// LoopPrism API, so they show up as live runs. It never gets in OpenCode's way: every request has a
// one second limit, errors are swallowed, and after a failure nothing is sent for ten seconds.
//
// Installed to ~/.config/opencode/plugins/ by `lpa install opencode` or the LoopPrism desktop app.
// Environment: LOOPPRISM_URL (default: ~/.loopprism/agent.json, else http://127.0.0.1:8080),
// LOOPPRISM_DISABLE=1, LOOPPRISM_NO_PROMPTS=1 (do not send prompt text).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const AGENT = "opencode";
const TIMEOUT_MS = 1000;
const BACKOFF_MS = 10_000;
const MAX_STRING = 4000;

function baseUrl() {
  if (process.env.LOOPPRISM_URL) return process.env.LOOPPRISM_URL.replace(/\/+$/, "");
  try {
    const url = JSON.parse(fs.readFileSync(path.join(os.homedir(), ".loopprism", "agent.json"), "utf8")).url;
    if (typeof url === "string" && url) return url.replace(/\/+$/, "");
  } catch {
    // no config file: the default
  }
  return "http://127.0.0.1:8080";
}

function clip(value, depth = 0) {
  if (typeof value === "string") {
    return value.length > MAX_STRING ? `${value.slice(0, MAX_STRING)}... [${value.length - MAX_STRING} more chars]` : value;
  }
  if (depth >= 6) return "...";
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => clip(v, depth + 1));
  if (value && typeof value === "object") {
    const out = {};
    for (const [k, v] of Object.entries(value).slice(0, 50)) out[k] = clip(v, depth + 1);
    return out;
  }
  return value;
}

let quietUntil = 0;
async function send(event) {
  if (process.env.LOOPPRISM_DISABLE === "1" || Date.now() < quietUntil) return;
  try {
    const res = await fetch(`${baseUrl()}/api/ingest/events`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events: [{ agent: AGENT, ...event }] }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch {
    quietUntil = Date.now() + BACKOFF_MS;
  }
}

export const LoopPrismPlugin = async ({ directory }) => {
  const started = new Map(); // callID -> start time
  const open = new Set(); // sessions with a run in progress
  const models = new Map(); // sessionID -> model id

  return {
    "chat.message": async (input, output) => {
      const sid = input.sessionID;
      if (!sid) return;
      const model = input.model?.modelID;
      if (model) models.set(sid, model);
      const text = (output.parts || [])
        .filter((p) => p && p.type === "text" && typeof p.text === "string" && !p.synthetic)
        .map((p) => p.text)
        .join("\n");
      open.add(sid);
      await send({
        event: "prompt",
        session_id: sid,
        cwd: directory,
        model,
        ...(process.env.LOOPPRISM_NO_PROMPTS ? {} : { prompt: clip(text) }),
      });
    },
    "tool.execute.before": async (input) => {
      if (input.callID) started.set(input.callID, Date.now());
    },
    "tool.execute.after": async (input, output) => {
      const t0 = started.get(input.callID);
      started.delete(input.callID);
      await send({
        event: "tool",
        session_id: input.sessionID,
        cwd: directory,
        model: models.get(input.sessionID),
        tool_name: input.tool,
        tool_input: clip(input.args),
        tool_use_id: input.callID,
        tool_response: clip(output?.output),
        duration_ms: t0 ? Date.now() - t0 : undefined,
      });
    },
    event: async ({ event }) => {
      const sid = event?.properties?.sessionID ?? event?.properties?.info?.id;
      if (!sid) return;
      if (event.type === "session.idle" && open.delete(sid)) {
        await send({ event: "stop", session_id: sid, cwd: directory, model: models.get(sid) });
      } else if (event.type === "session.error" && open.delete(sid)) {
        await send({ event: "stop", session_id: sid, cwd: directory, outcome: "failed" });
      } else if (event.type === "session.deleted") {
        open.delete(sid);
        models.delete(sid);
        await send({ event: "session_end", session_id: sid, cwd: directory });
      }
    },
  };
};
