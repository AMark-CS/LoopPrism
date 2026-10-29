const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { pickPort, HOST } = require("./ports");

const HEALTH_TIMEOUT_MS = 30_000;
const STABLE_AFTER_MS = 60_000;
const MAX_CONSECUTIVE_FAILURES = 5;
const STOP_GRACE_MS = 5_000;

// A route that exists in this version of the proxy. Raise it when a release adds the pages the app shows.
const REQUIRED_PROBE = "/api/sessions/optimize/settings";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function isHealthy(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function fetchJson(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(800) });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** Is `pid` alive and one of our lprism processes? */
function isLprism(pid, platform = process.platform) {
  try {
    process.kill(pid, 0);
  } catch {
    return false;
  }
  try {
    const { execFileSync } = require("node:child_process");
    if (platform === "win32") {
      // No `ps` on Windows; tasklist reports the image name (the command line isn't available).
      const out = execFileSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], {
        encoding: "utf8",
        windowsHide: true,
      });
      return /"lprism\.exe"/i.test(out);
    }
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
  constructor({ binary, logFile, pidFile, preferred }) {
    super();
    this.preferred = preferred; // { proxy, dashboard }
    this.binary = binary;
    this.logFile = logFile;
    this.pidFile = pidFile;
    this.child = null;
    this.stopping = false;
    this.failures = 0;
    this.ports = null;
    this.state = "stopped";
    this.runToken = 0;
    this.external = false; // using a LoopPrism someone else started
    this.watcher = null;
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
      external: this.external,
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

  /**
   * Is a LoopPrism (e.g. `lprism proxy` started from a terminal) already
   * serving the wanted ports? Then use it instead of starting a second proxy
   * that would fight over the database and the hooks' address.
   */
  async detectExternal() {
    const { proxy, dashboard } = this.preferred;
    const [p, d] = await Promise.all([
      fetchJson(`http://${HOST}:${proxy}/health`),
      fetchJson(`http://${HOST}:${dashboard}/api/health`),
    ]);
    // /health with a "backends" list is the proxy's signature.
    if (!(p?.status === "ok" && "backends" in p && d?.status === "ok")) return null;
    // An older LoopPrism left running (an old app's proxy, a `lprism proxy` from before an update)
    // serves an older dashboard that does not know the newer pages, which then show the wrong
    // content. Only reuse one that has this version's API; otherwise start our own on free ports.
    const current = await fetchJson(`http://${HOST}:${dashboard}${REQUIRED_PROBE}`);
    if (!current) {
      this.log(`an older LoopPrism is running on ${dashboard}; not using it`);
      return null;
    }
    return { proxy, dashboard };
  }

  adopt(token, ports) {
    this.ports = ports;
    this.external = true;
    this.failures = 0;
    this.log(`using existing LoopPrism: proxy ${this.proxyUrl}, dashboard ${this.dashboardUrl}`);
    this.setState("running");
    let misses = 0;
    this.watcher = setInterval(async () => {
      const ok = await fetchJson(`${this.dashboardUrl}/api/health`);
      misses = ok ? 0 : misses + 1;
      if (misses < 3 || token !== this.runToken) return;
      // It went away: take over with our own proxy.
      this.log("existing LoopPrism is gone; starting our own");
      this.clearWatcher();
      this.external = false;
      this.ports = null;
      if (!this.stopping) this.launch();
    }, 2000);
  }

  clearWatcher() {
    if (this.watcher) clearInterval(this.watcher);
    this.watcher = null;
  }

  async launch() {
    const token = ++this.runToken;
    this.clearWatcher();
    this.external = false;
    const existing = await this.detectExternal();
    if (token !== this.runToken || this.stopping) return false;
    if (existing) {
      this.adopt(token, existing);
      return true;
    }
    // Keep the same ports across restarts when they're still free so MCP
    // client configs and the open window stay valid.
    const proxy = await pickPort(
      this.ports?.proxy ?? this.preferred.proxy,
    );
    const dashboard = await pickPort(
      this.ports?.dashboard ?? this.preferred.dashboard,
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
      windowsHide: true, // no console window next to the app
      // UTF-8 for Python's stdout/log file: Windows would otherwise use the ANSI code page
      // and fail on the first non-ASCII character in a log line.
      env: { ...process.env, NO_COLOR: "1", PYTHONUNBUFFERED: "1", PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" },
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

  /** Change the wanted ports (settings) and restart on them. */
  async setPreferred(preferred) {
    this.preferred = preferred;
    this.ports = null;
    return this.restart();
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
    this.clearWatcher();
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

module.exports = { Sidecar, isLprism, REQUIRED_PROBE };
