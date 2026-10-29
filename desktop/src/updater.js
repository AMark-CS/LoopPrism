"use strict";
// Looks for a newer desktop release on GitHub and installs it in place.
//
// The app is not signed, so Electron's own auto-updater (which needs a signed
// app) is not an option. Instead: read the release list and download the
// installer for this machine (checking its size and SHA-256).
//   macOS:   copy the new app out of the .dmg, then let a tiny shell script swap
//            it in once this app has quit and start the new one.
//   Windows: run the downloaded NSIS installer silently once this app has quit;
//            it replaces the per-user install and starts the new version.
// Where that is not possible (not an installed app, folder not writable) the
// installer is saved to Downloads and opened for a manual install.

const crypto = require("node:crypto");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const { execFile, spawn } = require("node:child_process");
const { Readable } = require("node:stream");

const REPO = "AMark-CS/LoopPrism";
const TAG_PREFIX = "desktop-v";
const DEFAULT_API = `https://api.github.com/repos/${REPO}/releases?per_page=30`;
const DAY_MS = 24 * 60 * 60 * 1000;

/* ---------- versions and releases (pure) ---------- */

function parseVersion(text) {
  const m = /^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$/.exec(String(text ?? "").trim());
  return m ? { nums: [Number(m[1]), Number(m[2]), Number(m[3])], pre: m[4] ?? null } : null;
}

/** <0 when a is older than b. A pre-release is older than its release. */
function compareVersions(a, b) {
  const x = parseVersion(a);
  const y = parseVersion(b);
  if (!x || !y) throw new Error(`not a version: ${!x ? a : b}`);
  for (let i = 0; i < 3; i++) if (x.nums[i] !== y.nums[i]) return x.nums[i] - y.nums[i];
  if (x.pre === y.pre) return 0;
  if (x.pre === null) return 1;
  if (y.pre === null) return -1;
  return x.pre < y.pre ? -1 : 1;
}

/** The newest published desktop release in a GitHub release list. */
function pickLatest(releases, prefix = TAG_PREFIX) {
  let best = null;
  for (const r of Array.isArray(releases) ? releases : []) {
    if (!r || r.draft || r.prerelease || typeof r.tag_name !== "string" || !r.tag_name.startsWith(prefix)) continue;
    const version = r.tag_name.slice(prefix.length);
    if (!parseVersion(version)) continue;
    if (!best || compareVersions(version, best.version) > 0) best = { version, release: r };
  }
  return best;
}

const INSTALLER_EXT = { darwin: "dmg", win32: "exe" };

/** The installer for this platform and architecture (macOS dmg, Windows exe). */
function pickAsset(release, arch, platform = "darwin") {
  const ext = INSTALLER_EXT[platform];
  if (!ext) return null;
  const a = (release.assets ?? []).find((x) => typeof x.name === "string" && x.name.endsWith(`-${arch}.${ext}`));
  if (!a) return null;
  const digest = typeof a.digest === "string" && a.digest.startsWith("sha256:") ? a.digest.slice(7).toLowerCase() : null;
  return { name: a.name, url: a.browser_download_url, size: Number(a.size) || null, sha256: digest };
}

/** Only ever download from this repository's release assets. */
function isTrustedDownload(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && u.hostname === "github.com" && u.pathname.startsWith(`/${REPO}/releases/download/`);
  } catch {
    return false;
  }
}

async function fetchLatest({ fetchImpl, apiUrl = DEFAULT_API, current, arch, platform, timeoutMs = 10_000 }) {
  const res = await fetchImpl(apiUrl, {
    headers: { accept: "application/vnd.github+json", "user-agent": "LoopPrism-desktop" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`GitHub answered ${res.status}`);
  const latest = pickLatest(await res.json());
  if (!latest) return { current, latest: null, hasUpdate: false, releaseUrl: null, asset: null };
  return {
    current,
    latest: latest.version,
    hasUpdate: compareVersions(latest.version, current) > 0,
    releaseUrl: latest.release.html_url,
    asset: pickAsset(latest.release, arch, platform),
  };
}

/* ---------- download, stage, swap ---------- */

/** Remove a file if possible: a locked one (EBUSY) must not turn into a second error that hides the first. */
function rmQuiet(file) {
  try {
    fs.rmSync(file, { force: true });
  } catch {
    /* left behind; the next download picks another name */
  }
}

const LOCKED = new Set(["EBUSY", "EPERM", "EACCES", "UNKNOWN"]);

/** ``dest``, or a new name next to it when an old file of that name is there and cannot be removed (locked). */
function freshPath(dest) {
  try {
    fs.rmSync(dest, { force: true });
    return dest;
  } catch {
    const { dir, name, ext } = path.parse(dest);
    return path.join(dir, `${name}-${Date.now()}${ext}`);
  }
}

async function downloadAsset({ fetchImpl, asset, dest, onProgress, trusted = isTrustedDownload }) {
  if (!trusted(asset.url)) throw new Error("The download address is not on this project's GitHub releases");
  const res = await fetchImpl(asset.url, { headers: { "user-agent": "LoopPrism-desktop" } });
  if (!res.ok || !res.body) throw new Error(`Download failed (${res.status})`);
  const total = asset.size || Number(res.headers.get("content-length")) || 0;
  const hash = crypto.createHash("sha256");
  const out = fs.createWriteStream(dest);
  let got = 0;
  try {
    // A locked target (a half-finished earlier update, a virus scanner) fails here, not on the first write.
    await new Promise((resolve, reject) => {
      out.once("open", resolve);
      out.once("error", reject);
    });
    for await (const chunk of Readable.fromWeb(res.body)) {
      hash.update(chunk);
      got += chunk.length;
      if (!out.write(chunk)) await new Promise((r) => out.once("drain", r));
      onProgress?.(total ? Math.min(99, Math.floor((got / total) * 100)) : null);
    }
    await new Promise((resolve, reject) => out.end((err) => (err ? reject(err) : resolve())));
  } catch (err) {
    out.destroy();
    rmQuiet(dest);
    throw err;
  }
  const digest = hash.digest("hex");
  if (asset.size && got !== asset.size) {
    rmQuiet(dest);
    throw new Error("The download is incomplete");
  }
  if (asset.sha256 && digest !== asset.sha256) {
    rmQuiet(dest);
    throw new Error("The download does not match its checksum");
  }
  return { bytes: got, sha256: digest };
}

const run = (cmd, args) =>
  new Promise((resolve, reject) =>
    execFile(cmd, args, { timeout: 120_000 }, (err, stdout, stderr) =>
      err ? reject(new Error(`${cmd} failed: ${(stderr || err.message).trim()}`)) : resolve(stdout),
    ),
  );

/** Copy the app out of the dmg into stageDir; returns the staged bundle path. */
async function stageApp({ dmg, stageDir, mountDir, runImpl = run }) {
  fs.rmSync(stageDir, { recursive: true, force: true });
  fs.mkdirSync(stageDir, { recursive: true });
  fs.mkdirSync(mountDir, { recursive: true });
  await runImpl("hdiutil", ["attach", "-nobrowse", "-readonly", "-noverify", "-mountpoint", mountDir, dmg]);
  try {
    const app = fs.readdirSync(mountDir).find((n) => n.endsWith(".app"));
    if (!app) throw new Error("The installer contains no app");
    const staged = path.join(stageDir, app);
    await runImpl("ditto", [path.join(mountDir, app), staged]);
    return staged;
  } finally {
    await runImpl("hdiutil", ["detach", "-force", mountDir]).catch(() => {});
    fs.rmSync(mountDir, { recursive: true, force: true });
  }
}

const sh = (s) => `'${String(s).replace(/'/g, `'\\''`)}'`;

/**
 * Shell script that waits for this app to exit, swaps the bundle (keeping the
 * old one until the new one is in place), clears any quarantine flag and opens
 * the new app. If the swap fails the old app is put back and reopened.
 */
function installerScript({ pid, target, staged, stageDir, log }) {
  return `#!/bin/sh
exec >>${sh(log)} 2>&1
echo "update: waiting for $(date)"
i=0
while kill -0 ${Number(pid)} 2>/dev/null && [ $i -lt 200 ]; do sleep 0.3; i=$((i+1)); done
BACKUP=${sh(`${target}.previous`)}
rm -rf "$BACKUP"
if mv ${sh(target)} "$BACKUP"; then
  if mv ${sh(staged)} ${sh(target)}; then
    xattr -dr com.apple.quarantine ${sh(target)} 2>/dev/null
    rm -rf "$BACKUP" ${sh(stageDir)}
    echo "update: installed"
  else
    mv "$BACKUP" ${sh(target)}
    echo "update: could not move the new app in; restored the old one"
  fi
else
  echo "update: could not move the old app aside"
fi
open ${sh(target)}
`;
}

/** Command line for a silent in-place update with the NSIS installer. */
const windowsInstallerArgs = () => ["/S", "--updated", "--force-run"];

/* ---------- the updater ---------- */

class Updater extends EventEmitter {
  /**
   * @param {object} o
   * @param {string} o.current      running version
   * @param {string} o.arch         "arm64" | "x64"
   * @param {string} o.platform     process.platform
   * @param {string|null} o.bundle  path of the installed .app, or null when not running from one
   * @param {string} o.tmpDir
   * @param {string} o.downloadsDir
   * @param {number} o.pid
   * @param {Function} o.fetchImpl
   * @param {Function} o.openPath
   * @param {Function} o.openExternal
   * @param {Function} o.quit
   */
  constructor(o) {
    super();
    this.o = { apiUrl: DEFAULT_API, runImpl: run, spawnImpl: spawn, intervalMs: DAY_MS, now: Date.now, ...o };
    this.info = null;
    this.state = { phase: "idle", current: o.current, latest: null, releaseUrl: null, percent: null, error: null, auto: false };
  }

  set(patch) {
    this.state = { ...this.state, ...patch };
    this.emit("state", this.state);
  }

  /** Can the app replace itself? Needs an installed bundle in a folder we can write to. */
  canAutoInstall() {
    const { bundle, platform } = this.o;
    // Windows: the NSIS installer does the replacing, so any packaged app can update itself.
    if (platform === "win32") return Boolean(bundle);
    if (platform !== "darwin" || !bundle || !bundle.endsWith(".app")) return false;
    try {
      fs.accessSync(path.dirname(bundle), fs.constants.W_OK);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Show what the last check found, without asking GitHub. ``o.cache`` is
   * ``{ load(): {at, info} | null, save({at, info}) }`` so the answer survives restarts.
   */
  restore() {
    const c = this.o.cache?.load();
    if (!c?.info?.latest || !parseVersion(c.info.latest)) return;
    const info = { ...c.info, current: this.o.current };
    info.hasUpdate = compareVersions(info.latest, this.o.current) > 0;
    this.info = info;
    this.set({
      phase: info.hasUpdate ? "available" : "idle", latest: info.latest, releaseUrl: info.releaseUrl,
      auto: info.hasUpdate && Boolean(info.asset) && this.canAutoInstall(), checked: c.at,
    });
  }

  /** True when the last successful check is a day old (or there was none). */
  due() {
    const c = this.o.cache?.load();
    return !c || typeof c.at !== "number" || this.o.now() - c.at >= this.o.intervalMs;
  }

  /** The scheduled check: asks GitHub at most once a day. */
  async checkIfDue() {
    return this.due() ? this.check() : this.state;
  }

  /** Ask GitHub. Failures (offline, rate limit) leave things as they were; a manual check reports them. */
  async check({ manual = false } = {}) {
    if (["downloading", "installing"].includes(this.state.phase)) return this.state;
    try {
      const info = await fetchLatest({
        fetchImpl: this.o.fetchImpl, apiUrl: this.o.apiUrl, current: this.o.current, arch: this.o.arch, platform: this.o.platform,
      });
      this.info = info;
      this.o.cache?.save({ at: this.o.now(), info });
      this.set({
        phase: info.hasUpdate ? "available" : "idle",
        latest: info.latest,
        releaseUrl: info.releaseUrl,
        percent: null,
        error: null,
        auto: info.hasUpdate && Boolean(info.asset) && this.canAutoInstall(),
        checked: Date.now(),
      });
    } catch (err) {
      if (manual) this.set({ error: `Could not check for updates: ${err.message}`, checked: Date.now() });
    }
    return this.state;
  }

  /** Download the new version and install it (or hand over the dmg). */
  async install() {
    const info = this.info;
    if (!info?.hasUpdate) return this.state;
    if (!info.asset) {
      await this.o.openExternal(info.releaseUrl);
      return this.state;
    }
    if (["downloading", "installing"].includes(this.state.phase)) return this.state;
    if (this.state.phase === "downloaded" && this.state.file && fs.existsSync(this.state.file)) {
      await this.o.openPath(this.state.file); // already fetched: just show it again
      return this.state;
    }
    const auto = this.canAutoInstall();
    let dest = freshPath(path.join(auto ? this.o.tmpDir : this.o.downloadsDir, info.asset.name));
    try {
      this.set({ phase: "downloading", percent: 0, error: null });
      const download = () => downloadAsset({
        fetchImpl: this.o.fetchImpl, asset: info.asset, dest, trusted: this.o.trusted,
        onProgress: (p) => p !== null && p !== this.state.percent && this.set({ percent: p }),
      });
      try {
        await download();
      } catch (err) {
        if (!LOCKED.has(err?.code)) throw err;
        const { dir, name, ext } = path.parse(dest); // locked: try again under a name nobody holds
        dest = path.join(dir, `${name}-${Date.now()}${ext}`);
        await download();
      }
      if (!auto) {
        await this.o.openPath(dest);
        this.set({ phase: "downloaded", percent: 100, file: dest });
        return this.state;
      }
      this.set({ phase: "installing", percent: 100 });
      if (this.o.platform === "win32") {
        // Per-user NSIS, silent. `--updated` marks it as an update and `--force-run`
        // starts the new version afterwards (the same flags electron-updater uses).
        // A virus scanner often holds a fresh .exe for a moment: retry while it is locked.
        for (let attempt = 1; ; attempt++) {
          const child = this.o.spawnImpl(dest, windowsInstallerArgs(), { detached: true, stdio: "ignore" });
          const failure = await new Promise((resolve) => {
            if (typeof child.once !== "function") return resolve(null);
            child.once("error", resolve);
            child.once("spawn", () => resolve(null));
          });
          if (!failure) {
            child.unref();
            break;
          }
          if (!LOCKED.has(failure.code) || attempt >= 5) throw failure;
          await new Promise((r) => setTimeout(r, 1000));
        }
        this.o.quit();
        return this.state;
      }
      const target = this.o.bundle;
      const stageDir = path.join(path.dirname(target), `.LoopPrism-update-${info.latest}`);
      const mountDir = path.join(this.o.tmpDir, `loopprism-update-mount-${process.pid}`);
      const staged = await stageApp({ dmg: dest, stageDir, mountDir, runImpl: this.o.runImpl });
      rmQuiet(dest);
      const script = path.join(this.o.tmpDir, `loopprism-update-${info.latest}.sh`);
      fs.writeFileSync(script, installerScript({
        pid: this.o.pid, target, staged, stageDir, log: path.join(this.o.tmpDir, "loopprism-update.log"),
      }), { mode: 0o700 });
      const child = this.o.spawnImpl("/bin/sh", [script], { detached: true, stdio: "ignore" });
      child.unref();
      this.o.quit();
    } catch (err) {
      rmQuiet(dest);
      this.set({ phase: "error", error: err.message, percent: null });
    }
    return this.state;
  }
}

module.exports = {
  REPO, TAG_PREFIX, DEFAULT_API,
  parseVersion, compareVersions, pickLatest, pickAsset, isTrustedDownload, fetchLatest,
  downloadAsset, freshPath, stageApp, installerScript, windowsInstallerArgs, Updater,
};
