"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const u = require("../src/updater");

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "lp-upd-"));
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");

const release = (version, extra = {}) => ({
  tag_name: `desktop-v${version}`,
  html_url: `https://github.com/${u.REPO}/releases/tag/desktop-v${version}`,
  draft: false,
  prerelease: false,
  assets: [
    ...["arm64", "x64"].flatMap((arch) =>
      ["dmg", "zip"].map((ext) => ({
        name: `LoopPrism-${version}-${arch}.${ext}`,
        browser_download_url: `https://github.com/${u.REPO}/releases/download/desktop-v${version}/LoopPrism-${version}-${arch}.${ext}`,
        size: 1000,
        digest: `sha256:${"a".repeat(64)}`,
      })),
    ),
    // Windows: the installer (and the blockmap electron-builder may leave beside it, which must not match)
    ...[`LoopPrism-${version}-x64.exe.blockmap`, `LoopPrism-${version}-x64.exe`].map((name) => ({
      name,
      browser_download_url: `https://github.com/${u.REPO}/releases/download/desktop-v${version}/${name}`,
      size: 1000,
      digest: `sha256:${"b".repeat(64)}`,
    })),
  ],
  ...extra,
});

test("compareVersions orders releases and pre-releases", () => {
  const c = u.compareVersions;
  assert.ok(c("0.2.1", "0.2.0") > 0);
  assert.ok(c("0.10.0", "0.9.9") > 0); // numeric, not text, comparison
  assert.ok(c("1.0.0", "0.99.99") > 0);
  assert.equal(c("v0.2.0", "0.2.0"), 0);
  assert.ok(c("0.3.0-beta.1", "0.3.0") < 0);
  assert.ok(c("0.3.0-beta.2", "0.3.0-beta.1") > 0);
  assert.throws(() => c("nope", "0.1.0"));
});

test("pickLatest takes the newest published desktop release only", () => {
  const releases = [
    release("0.2.0"),
    release("0.3.0", { draft: true }),
    release("0.4.0", { prerelease: true }),
    { ...release("9.9.9"), tag_name: "npm-v9.9.9" },
    { ...release("1.0.0"), tag_name: "desktop-vbanana" },
    release("0.2.1"),
    release("0.1.9"),
  ];
  assert.equal(u.pickLatest(releases).version, "0.2.1");
  assert.equal(u.pickLatest([]), null);
  assert.equal(u.pickLatest(null), null);
});

test("pickAsset matches the architecture and reads the checksum", () => {
  const r = release("0.2.1");
  assert.equal(u.pickAsset(r, "arm64").name, "LoopPrism-0.2.1-arm64.dmg");
  assert.equal(u.pickAsset(r, "x64").name, "LoopPrism-0.2.1-x64.dmg");
  assert.equal(u.pickAsset(r, "arm64").sha256, "a".repeat(64));
  assert.equal(u.pickAsset(r, "ia32"), null);
  assert.equal(u.pickAsset(r, "arm64", "win32"), null); // no Windows on ARM build
  assert.equal(u.pickAsset(r, "x64", "win32").name, "LoopPrism-0.2.1-x64.exe");
  assert.equal(u.pickAsset(r, "x64", "win32").sha256, "b".repeat(64));
  assert.equal(u.pickAsset(r, "x64", "linux"), null);
  const noDigest = release("0.2.1");
  delete noDigest.assets[0].digest;
  assert.equal(u.pickAsset(noDigest, "arm64").sha256, null);
});

test("only this repository's release downloads are trusted", () => {
  const ok = `https://github.com/${u.REPO}/releases/download/desktop-v1.0.0/x.dmg`;
  assert.equal(u.isTrustedDownload(ok), true);
  for (const bad of [
    "http://github.com/AMark-CS/LoopPrism/releases/download/x/x.dmg",
    "https://evil.example/AMark-CS/LoopPrism/releases/download/x/x.dmg",
    "https://github.com/other/repo/releases/download/x/x.dmg",
    "https://github.com.evil.example/AMark-CS/LoopPrism/releases/download/x/x.dmg",
    "not a url",
  ]) assert.equal(u.isTrustedDownload(bad), false, bad);
});

const feed = (releases, status = 200) => async () => ({ ok: status === 200, status, json: async () => releases });

test("fetchLatest: update available, up to date, and failures", async () => {
  const base = { arch: "arm64", platform: "darwin" };
  const newer = await u.fetchLatest({ ...base, current: "0.2.0", fetchImpl: feed([release("0.2.1"), release("0.2.0")]) });
  assert.deepEqual([newer.hasUpdate, newer.latest, newer.asset.name], [true, "0.2.1", "LoopPrism-0.2.1-arm64.dmg"]);
  const same = await u.fetchLatest({ ...base, current: "0.2.1", fetchImpl: feed([release("0.2.1")]) });
  assert.equal(same.hasUpdate, false);
  const ahead = await u.fetchLatest({ ...base, current: "0.3.0", fetchImpl: feed([release("0.2.1")]) });
  assert.equal(ahead.hasUpdate, false); // a dev build is never "updated" backwards
  const none = await u.fetchLatest({ ...base, current: "0.2.0", fetchImpl: feed([]) });
  assert.deepEqual([none.hasUpdate, none.latest], [false, null]);
  await assert.rejects(u.fetchLatest({ ...base, current: "0.2.0", fetchImpl: feed([], 403) }), /403/);
});

/* ---- downloads against a real local server ---- */
function serve(body, { lie = 0 } = {}) {
  const server = http.createServer((req, res) => {
    res.setHeader("content-length", body.length);
    res.end(lie ? body.subarray(0, body.length - lie) : body);
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve({ server, url: `http://127.0.0.1:${server.address().port}/a.dmg` })),
  );
}
const trustAll = () => true;

test("downloadAsset verifies size and checksum, reports progress", async () => {
  const body = crypto.randomBytes(300_000);
  const { server, url } = await serve(body);
  const dest = path.join(tmp(), "a.dmg");
  const seen = [];
  const r = await u.downloadAsset({ fetchImpl: fetch, asset: { url, size: body.length, sha256: sha(body) }, dest, trusted: trustAll, onProgress: (p) => seen.push(p) });
  server.close();
  assert.equal(r.bytes, body.length);
  assert.ok(fs.readFileSync(dest).equals(body));
  assert.ok(seen.length > 0 && seen.every((p) => p >= 0 && p <= 99));
});

test("downloadAsset deletes a download with the wrong checksum or size", async () => {
  const body = crypto.randomBytes(5000);
  let s = await serve(body);
  let dest = path.join(tmp(), "bad.dmg");
  await assert.rejects(u.downloadAsset({ fetchImpl: fetch, asset: { url: s.url, size: body.length, sha256: "0".repeat(64) }, dest, trusted: trustAll }), /checksum/);
  assert.equal(fs.existsSync(dest), false);
  s.server.close();
  s = await serve(body);
  dest = path.join(tmp(), "short.dmg");
  await assert.rejects(u.downloadAsset({ fetchImpl: fetch, asset: { url: s.url, size: body.length + 10, sha256: null }, dest, trusted: trustAll }), /incomplete/);
  assert.equal(fs.existsSync(dest), false);
  s.server.close();
});

test("downloadAsset refuses addresses outside the project's releases", async () => {
  await assert.rejects(
    u.downloadAsset({ fetchImpl: () => assert.fail("must not fetch"), asset: { url: "https://evil.example/a.dmg" }, dest: path.join(tmp(), "x") }),
    /not on this project/,
  );
});

/* ---- the swap script, run for real against temp folders ---- */
function runScript({ target, staged, stageDir, pid }) {
  const dir = tmp();
  const bin = path.join(dir, "bin");
  fs.mkdirSync(bin);
  const opened = path.join(dir, "opened.txt");
  fs.writeFileSync(path.join(bin, "open"), `#!/bin/sh\necho "$@" >> '${opened}'\n`, { mode: 0o755 });
  const script = path.join(dir, "install.sh");
  fs.writeFileSync(script, u.installerScript({ pid, target, staged, stageDir, log: path.join(dir, "log.txt") }));
  spawnSync("/bin/sh", [script], { env: { PATH: `${bin}:/usr/bin:/bin` }, timeout: 20_000 });
  return { opened: fs.existsSync(opened) ? fs.readFileSync(opened, "utf8").trim() : null, log: fs.readFileSync(path.join(dir, "log.txt"), "utf8") };
}

function fakeApp(dir, name, version) {
  const app = path.join(dir, name);
  fs.mkdirSync(path.join(app, "Contents"), { recursive: true });
  fs.writeFileSync(path.join(app, "Contents", "version"), version);
  return app;
}

test("installer script swaps the app, drops the backup and reopens it", () => {
  const root = tmp();
  const target = fakeApp(root, "LoopPrism.app", "old");
  const stageDir = path.join(root, ".stage");
  const staged = fakeApp(stageDir, "LoopPrism.app", "new");
  const gone = spawnSync("true").pid; // a process that has already exited
  const r = runScript({ target, staged, stageDir, pid: gone });
  assert.equal(fs.readFileSync(path.join(target, "Contents", "version"), "utf8"), "new");
  assert.equal(fs.existsSync(`${target}.previous`), false);
  assert.equal(fs.existsSync(stageDir), false);
  assert.equal(r.opened, target);
  assert.match(r.log, /installed/);
});

test("installer script puts the old app back if the new one cannot be moved in", () => {
  const root = tmp();
  const target = fakeApp(root, "LoopPrism.app", "old");
  const r = runScript({ target, staged: path.join(root, "missing.app"), stageDir: path.join(root, ".stage"), pid: spawnSync("true").pid });
  assert.equal(fs.readFileSync(path.join(target, "Contents", "version"), "utf8"), "old");
  assert.equal(fs.existsSync(`${target}.previous`), false);
  assert.equal(r.opened, target);
  assert.match(r.log, /restored the old one/);
});

test("installer script quotes odd paths safely", () => {
  const root = tmp();
  const target = fakeApp(root, "Loop Prism's $(touch pwned).app", "old");
  const stageDir = path.join(root, ".stage dir");
  const staged = fakeApp(stageDir, "x.app", "new");
  runScript({ target, staged, stageDir, pid: spawnSync("true").pid });
  assert.equal(fs.readFileSync(path.join(target, "Contents", "version"), "utf8"), "new");
  assert.equal(fs.existsSync(path.join(process.cwd(), "pwned")), false);
});

test("stageApp copies the app out of the image and always unmounts", async () => {
  const root = tmp();
  const calls = [];
  const runImpl = async (cmd, args) => {
    calls.push([cmd, args[0]]);
    if (cmd === "hdiutil" && args[0] === "attach") fakeApp(args[args.indexOf("-mountpoint") + 1], "LoopPrism.app", "new");
    if (cmd === "ditto") fs.cpSync(args[0], args[1], { recursive: true });
  };
  const staged = await u.stageApp({ dmg: "x.dmg", stageDir: path.join(root, "stage"), mountDir: path.join(root, "mnt"), runImpl });
  assert.equal(fs.readFileSync(path.join(staged, "Contents", "version"), "utf8"), "new");
  assert.deepEqual(calls.map((c) => c.join(" ")), ["hdiutil attach", "ditto undefined", "hdiutil detach"].map((x, i) => (i === 1 ? `ditto ${calls[1][1]}` : x)));
  assert.equal(fs.existsSync(path.join(root, "mnt")), false);

  const failing = async (cmd, args) => { if (cmd === "hdiutil" && args[0] === "attach") fs.mkdirSync(args[args.indexOf("-mountpoint") + 1], { recursive: true }); };
  await assert.rejects(u.stageApp({ dmg: "x.dmg", stageDir: path.join(root, "s2"), mountDir: path.join(root, "m2"), runImpl: failing }), /no app/);
});

/* ---- the state machine ---- */
async function updaterWith(over = {}) {
  const body = crypto.randomBytes(20_000);
  const { server, url } = await serve(body);
  const root = tmp();
  const rel = release("0.2.1");
  const want = u.pickAsset(rel, over.arch ?? "arm64", over.platform ?? "darwin");
  const at = rel.assets.findIndex((a) => a.name === want?.name);
  if (at >= 0) rel.assets[at] = { ...rel.assets[at], browser_download_url: url, size: body.length, digest: `sha256:${sha(body)}` };
  const calls = { opened: [], external: [], spawned: [], quit: 0 };
  const up = new u.Updater({
    current: "0.2.0", arch: "arm64", platform: "darwin", bundle: null,
    tmpDir: path.join(root, "tmp"), downloadsDir: path.join(root, "dl"), pid: 4242,
    fetchImpl: async (target, opts) => (String(target).includes("api") ? { ok: true, status: 200, json: async () => [rel] } : fetch(target, opts)),
    apiUrl: "http://api.test/releases", trusted: trustAll,
    openPath: async (p) => calls.opened.push(p), openExternal: async (x) => calls.external.push(x), quit: () => calls.quit++,
    runImpl: async (cmd, args) => {
      if (cmd === "hdiutil" && args[0] === "attach") fakeApp(args[args.indexOf("-mountpoint") + 1], "LoopPrism.app", "new");
      if (cmd === "ditto") fs.cpSync(args[0], args[1], { recursive: true });
    },
    spawnImpl: (cmd, args) => { calls.spawned.push([cmd, args]); return { unref() {} }; },
    ...over,
  });
  fs.mkdirSync(up.o.tmpDir, { recursive: true });
  fs.mkdirSync(up.o.downloadsDir, { recursive: true });
  return { up, calls, root, close: () => server.close() };
}

test("no update: nothing to show and install does nothing", async () => {
  const { up, calls, close } = await updaterWith({ current: "0.2.1" });
  await up.check();
  assert.equal(up.state.phase, "idle");
  await up.install();
  assert.deepEqual([calls.opened, calls.external, calls.quit], [[], [], 0]);
  close();
});

test("a failed check stays quiet unless the user asked", async () => {
  const { up, close } = await updaterWith({ fetchImpl: async () => { throw new Error("offline"); } });
  await up.check();
  assert.deepEqual([up.state.phase, up.state.error], ["idle", null]);
  await up.check({ manual: true });
  assert.match(up.state.error, /offline/);
  close();
});

test("update available but the app cannot replace itself: the dmg is saved and opened", async () => {
  const { up, calls, close } = await updaterWith({ bundle: null });
  const states = [];
  up.on("state", (s) => states.push(s.phase));
  await up.check();
  assert.deepEqual([up.state.phase, up.state.latest, up.state.auto], ["available", "0.2.1", false]);
  await up.install();
  assert.equal(up.state.phase, "downloaded");
  assert.equal(path.dirname(calls.opened[0]), up.o.downloadsDir);
  assert.ok(states.includes("downloading"));
  await up.install(); // "Open installer" again: opens the same file, no second download
  assert.equal(calls.opened.length, 2);
  close();
});

test("update available and writable install: stages, writes the swap script, spawns it and quits", async () => {
  const root = tmp();
  const bundle = fakeApp(root, "LoopPrism.app", "old");
  const { up, calls, close } = await updaterWith({ bundle });
  await up.check();
  assert.equal(up.state.auto, true);
  await up.install();
  assert.equal(calls.quit, 1);
  assert.equal(calls.spawned.length, 1);
  const script = fs.readFileSync(calls.spawned[0][1][0], "utf8");
  assert.match(script, /kill -0 4242/);
  assert.match(script, /\.LoopPrism-update-0\.2\.1/);
  // the new app is staged next to the old one, which is untouched until the script runs
  assert.equal(fs.readFileSync(path.join(bundle, "Contents", "version"), "utf8"), "old");
  assert.ok(fs.existsSync(path.join(root, ".LoopPrism-update-0.2.1", "LoopPrism.app")));
  close();
});

test("Windows: an installed app runs the silent installer once it has quit, and nothing is staged", async () => {
  const root = tmp();
  const exe = path.join(root, "LoopPrism.exe");
  fs.writeFileSync(exe, "old");
  const { up, calls, close } = await updaterWith({ platform: "win32", arch: "x64", bundle: exe });
  await up.check();
  assert.deepEqual([up.state.phase, up.state.auto], ["available", true]);
  await up.install();
  assert.equal(calls.quit, 1);
  assert.equal(calls.spawned.length, 1);
  const [cmd, args] = calls.spawned[0];
  assert.equal(path.basename(cmd), "LoopPrism-0.2.1-x64.exe");
  assert.equal(path.dirname(cmd), up.o.tmpDir);
  assert.ok(fs.existsSync(cmd)); // the installer is still there for the spawned process
  assert.deepEqual(args, u.windowsInstallerArgs());
  assert.deepEqual(args, ["/S", "--updated", "--force-run"]);
  assert.equal(fs.readFileSync(exe, "utf8"), "old"); // the installer replaces it, not us
  close();
});

test("Windows: a copy that is not installed (dev run) saves the installer and opens it", async () => {
  const { up, calls, close } = await updaterWith({ platform: "win32", arch: "x64", bundle: null });
  await up.check();
  assert.equal(up.state.auto, false);
  await up.install();
  assert.equal(up.state.phase, "downloaded");
  assert.equal(path.dirname(calls.opened[0]), up.o.downloadsDir);
  assert.deepEqual([calls.spawned.length, calls.quit], [0, 0]);
  close();
});

test("a failing download reports an error and can be retried", async () => {
  const { up, calls, close } = await updaterWith();
  await up.check();
  up.info.asset.sha256 = "f".repeat(64);
  await up.install();
  assert.equal(up.state.phase, "error");
  assert.match(up.state.error, /checksum/);
  assert.equal(calls.quit, 0);
  close();
});

test("with no installer for this Mac the release page opens instead", async () => {
  const { up, calls, close } = await updaterWith({ arch: "ia32" });
  await up.check();
  assert.equal(up.state.phase, "available");
  await up.install();
  assert.equal(calls.external.length, 1);
  close();
});

/* ---- once a day ---- */
test("the scheduled check asks GitHub at most once a day and remembers the answer", async () => {
  let stored = null;
  let asked = 0;
  let clock = 1_000_000;
  const mk = () => new u.Updater({
    current: "0.2.0", arch: "arm64", platform: "darwin", bundle: null, tmpDir: tmp(), downloadsDir: tmp(), pid: 1,
    fetchImpl: async () => { asked++; return { ok: true, status: 200, json: async () => [release("0.2.1")] }; },
    cache: { load: () => stored, save: (c) => { stored = c; } }, now: () => clock,
  });
  const first = mk();
  await first.checkIfDue();
  assert.deepEqual([asked, first.state.phase], [1, "available"]);

  clock += 23 * 3600_000; // same day, e.g. the app was reopened
  const reopened = mk();
  reopened.restore();
  assert.equal(reopened.state.phase, "available"); // the button is back without asking again
  await reopened.checkIfDue();
  assert.equal(asked, 1);

  clock += 2 * 3600_000; // now more than a day since the check
  await reopened.checkIfDue();
  assert.equal(asked, 2);

  await reopened.check({ manual: true }); // a manual check always asks
  assert.equal(asked, 3);
});

test("a cached update disappears once the app is that version, and failed checks are retried", async () => {
  let stored = { at: 5, info: { latest: "0.2.1", hasUpdate: true, releaseUrl: "x", asset: null } };
  const up = new u.Updater({
    current: "0.2.1", arch: "arm64", platform: "darwin", bundle: null, tmpDir: tmp(), downloadsDir: tmp(), pid: 1,
    fetchImpl: async () => { throw new Error("offline"); }, cache: { load: () => stored, save: (c) => { stored = c; } }, now: () => 6,
  });
  up.restore();
  assert.equal(up.state.phase, "idle"); // already on 0.2.1: no button

  stored = null; // nothing cached (first run, or the last check failed) -> due
  assert.equal(up.due(), true);
  await up.checkIfDue();
  assert.equal(stored, null); // a failure is not remembered, so the next tick retries
});
