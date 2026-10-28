const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { pickPort, HOST } = require("./ports");

const PREFERRED_PROXY_PORT = 4317;
const PREFERRED_DASHBOARD_PORT = 8080;
const HEALTH_TIMEOUT_MS = 30_000;
const STABLE_AFTER_MS = 60_000;
const MAX_CONSECUTIVE_FAILURES = 5;
const STOP_GRACE_MS = 5_000;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function isHealthy(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1000) });
    return res.ok;
  } catch {
    return false;
  }
}

/** Is `pid` alive and one of our lprism processes? */
function isLprism(pid) {
  try {
    process.kill(pid, 0);
  } catch {
    return false;
  }
  try {
    const { execFileSync } = require("node:child_process");
    const cmd = execFileSync("ps", ["-p", String(pid), "-o", "command="], {
      encoding: "utf8",
    });
    return /lprism/.test(cmd) && /\bproxy\b/.test(cmd);
  } catch {
    return false;
  }
}

/**
 * Runs and supervises the frozen `lprism proxy` process.
 *
 * Emits "status" with { state, proxyUrl, dashboardUrl, message } where state is
 * one of: starting | running | restarting | failed | stopped.
 */
class Sidecar extends EventEmitter {
  constructor({ binary, logFile, pidFile }) {
    super();
    this.binary = binary;
    this.logFile = logFile;
    this.pidFile = pidFile;
    this.child = null;
    this.stopping = false;
    this.failures = 0;
    this.ports = null;
    this.state = "stopped";
    this.runToken = 0;
  }

  get proxyUrl() {
    return this.ports ? `http://${HOST}:${this.ports.proxy}` : null;
  }

  get dashboardUrl() {
    return this.ports ? `http://${HOST}:${this.ports.dashboard}` : null;
  }

  setState(state, message = "") {
    this.state = state;
    this.emit("status", {
      state,
      proxyUrl: this.proxyUrl,
      dashboardUrl: this.dashboardUrl,
      message,
    });
  }

  log(line) {
    try {
      fs.appendFileSync(
        this.logFile,
        `[${new Date().toISOString()}] [desktop] ${line}\n`,
      );
    } catch {
      /* logging must never break the app */
    }
  }

  /** Kill a sidecar left behind by a previous app instance that died hard. */
  async reapStale() {
    let pid;
    try {
      pid = parseInt(fs.readFileSync(this.pidFile, "utf8"), 10);
    } catch {
      return;
    }
    if (pid && isLprism(pid)) {
      this.log(`killing stale sidecar pid ${pid}`);
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        /* already gone */
      }
      // Let it release its ports so we can reuse 4317/8080.
      for (let i = 0; i < 30 && isLprism(pid); i++) await sleep(100);
      if (isLprism(pid)) process.kill(pid, "SIGKILL");
    }
    fs.rmSync(this.pidFile, { force: true });
  }

  async start() {
    this.stopping = false;
    await this.reapStale();
    return this.launch();
  }

  async launch() {
    const token = ++this.runToken;
    // Keep the same ports across restarts when they're still free so MCP
    // client configs and the open window stay valid.
    const proxy = await pickPort(
      this.ports?.proxy ?? PREFERRED_PROXY_PORT,
    );
    const dashboard = await pickPort(
      this.ports?.dashboard ?? PREFERRED_DASHBOARD_PORT,
      [proxy],
    );
    this.ports = { proxy, dashboard };
    this.setState(this.failures ? "restarting" : "starting");

    fs.mkdirSync(path.dirname(this.logFile), { recursive: true });
    const out = fs.openSync(this.logFile, "a");
    // No --db: use the CLI default (~/.loopprism/traces.db) so the app and
    // `lprism proxy` share data. LOOPPRISM_DB_PATH still overrides it.
    const args = [
      "proxy",
      "--port",
      String(proxy),
      "--dashboard-port",
      String(dashboard),
    ];
    this.log(`spawn ${this.binary} ${args.join(" ")}`);
    const child = spawn(this.binary, args, {
      stdio: ["ignore", out, out],
      env: { ...process.env, NO_COLOR: "1", PYTHONUNBUFFERED: "1" },
    });
    fs.closeSync(out);
    this.child = child;
    const startedAt = Date.now();

    const exited = new Promise((resolve) => {
      child.once("error", (err) => {
        this.log(`spawn error: ${err.message}`);
        resolve({ code: null, signal: null, error: err });
      });
      child.once("exit", (code, signal) => resolve({ code, signal }));
    });
    exited.then((info) => this.onExit(token, child, startedAt, info));

    if (child.pid) fs.writeFileSync(this.pidFile, String(child.pid));

    const ready = await this.waitHealthy(token, exited);
    if (ready && token === this.runToken && !this.stopping) {
      this.log(`healthy: proxy ${this.proxyUrl}, dashboard ${this.dashboardUrl}`);
      this.setState("running");
    }
    return ready;
  }

  async waitHealthy(token, exited) {
    let done = false;
    exited.then(() => {
      done = true;
    });
    const deadline = Date.now() + HEALTH_TIMEOUT_MS;
    while (!done && !this.stopping && token === this.runToken) {
      if (Date.now() > deadline) {
        this.log("health check timed out; killing sidecar");
        this.child?.kill("SIGKILL");
        return false;
      }
      const [p, d] = await Promise.all([
        isHealthy(`${this.proxyUrl}/health`),
        isHealthy(`${this.dashboardUrl}/api/health`),
      ]);
      if (p && d) return true;
      await sleep(250);
    }
    return false;
  }

  async onExit(token, child, startedAt, { code, signal, error }) {
    if (this.child === child) this.child = null;
    fs.rmSync(this.pidFile, { force: true });
    this.log(`sidecar exited code=${code} signal=${signal}`);
    if (this.stopping || token !== this.runToken) return;

    if (Date.now() - startedAt > STABLE_AFTER_MS) this.failures = 0;
    this.failures += 1;
    if (this.failures > MAX_CONSECUTIVE_FAILURES) {
      this.setState(
        "failed",
        error ? error.message : `proxy exited (code ${code ?? signal})`,
      );
      return;
    }
    const delay = Math.min(1000 * 2 ** (this.failures - 1), 10_000);
    this.setState("restarting");
    await sleep(delay);
    if (this.stopping || token !== this.runToken) return;
    await this.launch();
  }

  /** Manual restart (tray menu); also recovers from the "failed" state. */
  async restart() {
    await this.stopChild();
    this.failures = 0;
    this.stopping = false;
    return this.launch();
  }

  async stopChild() {
    this.runToken++; // invalidate pending health waits / restarts
    const child = this.child;
    if (!child || child.exitCode !== null || child.signalCode !== null) return;
    const gone = new Promise((resolve) => child.once("exit", resolve));
    child.kill("SIGTERM");
    const timer = setTimeout(() => child.kill("SIGKILL"), STOP_GRACE_MS);
    await gone;
    clearTimeout(timer);
  }

  async stop() {
    this.stopping = true;
    await this.stopChild();
    fs.rmSync(this.pidFile, { force: true });
    this.setState("stopped");
  }

  /** Synchronous last-resort kill for process 'exit' / signal handlers. */
  killNow() {
    this.stopping = true;
    try {
      this.child?.kill("SIGKILL");
    } catch {
      /* ignore */
    }
    fs.rmSync(this.pidFile, { force: true });
  }
}

module.exports = { Sidecar };
