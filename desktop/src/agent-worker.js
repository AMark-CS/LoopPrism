// Runs in a child process (Electron's node, ELECTRON_RUN_AS_NODE=1) because the
// hook installers shell out to `claude` with spawnSync, which would freeze the
// app's main process for seconds.
//
//   agent-worker.js status | install <claude|codex> | uninstall <claude|codex>
//
// Prints one JSON object on stdout. LPRISM_AGENT_ROOT points at the bundled
// copy of the repo's npm/ package (lib/, plugin/, .claude-plugin/).
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = process.env.LPRISM_AGENT_ROOT;
const claude = require(path.join(root, "lib", "claude"));
const codex = require(path.join(root, "lib", "codex"));
const workbuddy = require(path.join(root, "lib", "workbuddy"));
const { codexHome } = require(path.join(root, "lib", "paths"));

function hasCli(name) {
  // On Windows `codex` is usually a .cmd shim, which only runs through a shell.
  const r = spawnSync(name, ["--version"], { encoding: "utf8", shell: process.platform === "win32", windowsHide: true });
  return !r.error && r.status === 0;
}

function status() {
  const out = {};
  const claudeCli = claude.available();
  out.claude = {
    cli: claudeCli,
    found: claudeCli || fs.existsSync(path.join(os.homedir(), ".claude")),
    connected: false,
  };
  if (claudeCli) out.claude.connected = claude.isInstalled();
  out.codex = {
    cli: hasCli("codex"),
    found: false,
    connected: false,
  };
  out.codex.found = out.codex.cli || fs.existsSync(codexHome());
  try {
    out.codex.connected = codex.isInstalled();
  } catch (err) {
    out.codex.error = err.message;
  }
  out.workbuddy = { cli: false, found: false, connected: false };
  try {
    out.workbuddy.found = workbuddy.available();
    out.workbuddy.connected = workbuddy.isInstalled();
  } catch (err) {
    out.workbuddy.error = err.message;
  }
  return out;
}

function run(action, target) {
  const mod = { claude, codex, workbuddy }[target];
  if (!mod) throw new Error(`unknown app: ${target}`);
  if (action === "install") mod.install();
  else if (action === "uninstall") mod.uninstall();
  else throw new Error(`unknown action: ${action}`);
  return { ok: true };
}

try {
  const [action, target] = process.argv.slice(2);
  const result = action === "status" ? status() : run(action, target);
  process.stdout.write(JSON.stringify(result));
} catch (err) {
  process.stdout.write(JSON.stringify({ error: err.message }));
}
