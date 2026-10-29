#!/usr/bin/env node
// Freeze the `lprism` CLI with PyInstaller into desktop/sidecar/dist/lprism/.
//
// Builds the dashboard (dashboard/dist), then runs PyInstaller with $PYTHON
// (default: python3, or python on Windows), which must already have loopprism
// and pyinstaller installed:
//   pip install "$REPO_ROOT" pyinstaller
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const win = process.platform === "win32";
const here = path.resolve(__dirname, "..");
const python = process.env.PYTHON || (win ? "python" : "python3");

function run(cmd, args, cwd) {
  // npm is a .cmd shim on Windows, which only runs through a shell.
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit", shell: win && cmd === "npm" });
  if (r.error) throw r.error;
  if (r.status !== 0) process.exit(r.status ?? 1);
}

// The sidecar bundles a fresh build of the dashboard (see sidecar/lprism.spec).
const dashboard = path.join(here, "..", "dashboard");
if (!fs.existsSync(path.join(dashboard, "node_modules"))) run("npm", ["ci"], dashboard);
run("npm", ["run", "build"], dashboard);

const sidecar = path.join(here, "sidecar");
for (const d of ["dist", "build"]) fs.rmSync(path.join(sidecar, d), { recursive: true, force: true });
run(python, ["-m", "PyInstaller", "--noconfirm", "--clean", "lprism.spec"], sidecar);

// Smoke test the frozen binary.
run(path.join(sidecar, "dist", "lprism", win ? "lprism.exe" : "lprism"), ["--version"], sidecar);
