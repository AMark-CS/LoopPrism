const { execFile } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { app } = require("electron");

const AGENTS = [
  {
    id: "claude",
    name: "Claude Code",
    blurb:
      "Records every prompt, tool call and error as a run. Installs the LoopPrism plugin through the claude CLI.",
    afterConnect: "Restart running Claude Code sessions to start recording.",
  },
  {
    id: "codex",
    name: "Codex",
    blurb:
      "Records every prompt, tool call and error as a run. Adds hooks to ~/.codex/hooks.json.",
    afterConnect:
      "Open Codex and run /hooks once to review and trust the LoopPrism hooks.",
  },
];

function agentRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "agent-hooks")
    : path.join(__dirname, "..", "..", "npm");
}

let cachedPath = null;

/**
 * Apps launched from Finder get a bare PATH, so `claude` and `node` installed
 * by Homebrew, nvm or the Claude installer wouldn't be found. Ask the user's
 * login shell for the real PATH.
 */
function loginShellPath() {
  if (cachedPath) return Promise.resolve(cachedPath);
  const home = os.homedir();
  const extras = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    path.join(home, ".local", "bin"),
    path.join(home, ".claude", "local"),
    path.join(home, ".npm-global", "bin"),
    path.join(home, ".bun", "bin"),
  ];
  const fallback = [...extras, process.env.PATH || ""].join(":");
  return new Promise((resolve) => {
    execFile(
      process.env.SHELL || "/bin/zsh",
      ["-ilc", 'printf "__LP__%s__LP__" "$PATH"'],
      { timeout: 5000, encoding: "utf8" },
      (err, stdout) => {
        const m = /__LP__(.*)__LP__/s.exec(stdout || "");
        const shellPath = !err && m ? m[1] : "";
        cachedPath = [shellPath, fallback].filter(Boolean).join(":");
        resolve(cachedPath);
      },
    );
  });
}

async function worker(...args) {
  const PATH = await loginShellPath();
  return new Promise((resolve) => {
    execFile(
      process.execPath,
      [path.join(__dirname, "agent-worker.js"), ...args],
      {
        timeout: 60_000,
        encoding: "utf8",
        env: {
          ...process.env,
          PATH,
          ELECTRON_RUN_AS_NODE: "1",
          LPRISM_AGENT_ROOT: agentRoot(),
        },
      },
      (err, stdout, stderr) => {
        try {
          resolve(JSON.parse(stdout));
        } catch {
          resolve({ error: (stderr || err?.message || "worker failed").trim() });
        }
      },
    );
  });
}

/** Fingerprint of the bundled hook scripts, to notice when the app updated them. */
function bundleHash() {
  const hash = require("node:crypto").createHash("sha256");
  const dir = path.join(agentRoot(), "plugin");
  const walk = (d) => {
    for (const f of fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const p = path.join(d, f.name);
      if (f.isDirectory()) walk(p);
      else hash.update(f.name).update(fs.readFileSync(p));
    }
  };
  try {
    walk(dir);
  } catch {
    return "none";
  }
  return hash.digest("hex").slice(0, 16);
}

const status = () => worker("status");
const connect = (id) => worker("install", id);
const disconnect = (id) => worker("uninstall", id);

/** Latest run time per agent, from the dashboard API (timestamps are UTC). */
async function lastSeen(dashboardUrl) {
  const seen = {};
  if (!dashboardUrl) return seen;
  try {
    const res = await fetch(`${dashboardUrl}/api/traces?limit=100`, {
      signal: AbortSignal.timeout(2000),
    });
    const { traces } = await res.json();
    for (const t of traces) {
      let agent;
      try {
        agent = JSON.parse(t.tags || "{}").agent;
      } catch {
        continue;
      }
      const key = { "claude-code": "claude", codex: "codex" }[agent];
      const at = Date.parse(`${String(t.timestamp).replace(" ", "T")}Z`);
      if (key && (!seen[key] || at > seen[key])) seen[key] = at;
    }
  } catch {
    /* proxy down: no activity info */
  }
  return seen;
}

/**
 * The hooks read the API address from ~/.loopprism/agent.json (or
 * LOOPPRISM_URL). The app's dashboard moves off 8080 when that port is taken,
 * so while it runs the file points at the real address. Entries the app wrote
 * carry a marker, so it never overwrites an address the user chose (for example
 * with `lpa install --url`), and cleans up its own after a crash or quit.
 */
const agentJson = () => path.join(os.homedir(), ".loopprism", "agent.json");
const DEFAULT_URL = "http://127.0.0.1:8080";
const MARKER = "loopprism-desktop";

function readAgentJson() {
  try {
    return JSON.parse(fs.readFileSync(agentJson(), "utf8")) || {};
  } catch {
    return {};
  }
}

function writeAgentJson(config) {
  const file = agentJson();
  if (Object.keys(config).length === 0) {
    fs.rmSync(file, { force: true });
    return;
  }
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(config, null, 2)}\n`);
}

function withoutOurs(config) {
  const { url, managedBy, ...rest } = config;
  return rest;
}

function syncHookUrl(dashboardUrl) {
  const current = readAgentJson();
  const mine = current.managedBy === MARKER;
  if (dashboardUrl && dashboardUrl !== DEFAULT_URL) {
    if (current.url && !mine && current.url !== dashboardUrl) return; // user's own
    writeAgentJson({ ...current, url: dashboardUrl, managedBy: MARKER });
  } else if (mine) {
    writeAgentJson(withoutOurs(current));
  }
}

/** Where do the hooks send events, and is that this app? */
function hookTarget(dashboardUrl) {
  const url = String(readAgentJson().url || DEFAULT_URL).replace(/\/+$/, "");
  return { url, matches: !dashboardUrl || url === dashboardUrl };
}

/** Force the hooks to this app's address (the user asked to). */
function pointHooksHere(dashboardUrl) {
  const current = readAgentJson();
  if (dashboardUrl === DEFAULT_URL) {
    writeAgentJson(withoutOurs(current));
  } else {
    writeAgentJson({ ...current, url: dashboardUrl, managedBy: MARKER });
  }
}

module.exports = { bundleHash, AGENTS, status, connect, disconnect, lastSeen, syncHookUrl, hookTarget, pointHooksHere };
