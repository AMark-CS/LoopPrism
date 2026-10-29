# LoopPrism Desktop

A macOS and Windows app that bundles the LoopPrism MCP proxy and dashboard — no Python,
no terminal. It runs `lprism proxy` (frozen with PyInstaller) as a background
sidecar, opens the dashboard in a window, and keeps the proxy running from the
menu bar (macOS) or system tray (Windows).

## Install

### Windows (x64)

1. Download `LoopPrism-<version>-x64.exe` from the [Releases](https://github.com/AMark-CS/LoopPrism/releases/latest) page and run it.
   The installer is a short wizard: you can choose the **install folder**, and whether to install for just
   you (the default, no administrator prompt) or for all users of the PC. LoopPrism starts when it finishes.
   For a scripted install, `LoopPrism-<version>-x64.exe /S /D=C:\Tools\LoopPrism` installs silently into
   that folder (`/D=` must be the last argument).
2. The installer is not code-signed, so Windows SmartScreen may say "Windows protected your PC":
   click **More info → Run anyway**.
3. Closing the window keeps LoopPrism in the system tray (bottom right, maybe under the `^`);
   right-click the icon for the menu, click it to reopen the window.

### macOS

1. Download `LoopPrism-<version>-arm64.dmg` (Apple Silicon) or `-x64.dmg`
   (Intel) from the [Releases](https://github.com/AMark-CS/LoopPrism/releases) page.
2. Drag **LoopPrism** into **Applications**.
3. First launch — the app is not notarized (see below), so macOS blocks it:
   - Right-click (or Control-click) **LoopPrism.app** → **Open** → **Open**, or
   - run `xattr -dr com.apple.quarantine /Applications/LoopPrism.app`, or
   - open **System Settings → Privacy & Security** and click **Open Anyway**.

## Using it

- **Sessions** page (opens first): browse, search and export your Claude Code, Codex, DeepSeek Harness
  and WorkBuddy sessions, and inspect each one's chat, trajectory and context. Claude Code and Codex
  sessions can also be resumed and deleted here; DeepSeek Harness and WorkBuddy ones are read-only
  (resume or delete them in their own app). **Cost** adds up what every agent spent, by day, model,
  agent and project. Runs recorded by the proxy and the hooks, including MCP tool calls, are in the run
  viewer linked at the bottom of that page.
- **Apps** page: switch on **Claude Code**, **Codex** and/or **WorkBuddy** and LoopPrism starts
  recording their prompts, tool calls and errors. The first time you open the
  app it offers to enable every app it finds. Switching one off removes its
  hook again. (This runs the same installers as `npx loopprism install`,
  bundled from `../npm`.) For Codex, run `/hooks` once afterwards to trust the
  hooks; for Claude Code, restart running sessions.
- Other MCP clients that use HTTP servers can be pointed at the proxy; the Apps
  page builds the URL for you.
- **Estimated cost** in the Runs header and on each run is the turn's token usage priced at the
  providers' current API prices (updated with the app). Subscription plans bill differently, so read it as
  "what this would cost on the API".
- **Settings** page: proxy/dashboard ports, theme (**Dark**, **Light** or **System**, which follows the
  operating system), open at login, where the data lives. Dark is the default.
- On Windows the **Resume** button in Sessions opens a new console window, and **Delete** sends the
  session to the Recycle Bin.

- Point your MCP clients at `http://127.0.0.1:4317/<server-name>`. The menu bar
  icon has **Copy proxy URL** with the exact address.
- If 4317 (proxy) or 8080 (dashboard) is taken, the app picks free ports; the
  menu bar menu always shows the real proxy URL.
- Closing the window keeps the proxy running; **Open dashboard** reopens it.
  **Quit LoopPrism** (menu bar or ⌘Q) stops the proxy.
- If the proxy crashes it is restarted automatically (with backoff). **Restart
  proxy** in the menu forces a restart.
- Traces are stored in `~/.loopprism/traces.db`, the same default as the
  `lprism` CLI, so the app and CLI share data. (`LOOPPRISM_DB_PATH` overrides it.)
- Sidecar logs: `~/Library/Logs/LoopPrism/sidecar.log` on macOS, `%APPDATA%\LoopPrism\logs\sidecar.log` on Windows (**Show logs** in the menu).

## Updates

The app checks this repository's GitHub releases at most once a day (a few seconds after launch
when a day has passed since the last check; the last answer is remembered across restarts). When a newer `desktop-v*` release exists, an **Update to x.y.z** button appears in the
sidebar above the proxy status; when you are on the latest version there is no button.
**Settings → Updates → Check for updates** checks on demand.

Clicking the button downloads the installer for this machine's platform and architecture and
checks its size and SHA-256 against the release. On macOS it then copies the new app out of the
`.dmg`, quits, swaps the app in place and reopens it; if the app is not in a folder it can write
to (for example it was installed by an administrator), the `.dmg` is saved to Downloads and opened
so you can drag it into Applications yourself. On Windows it quits and runs the installer silently, which
replaces the app in the folder it was installed to and starts the new version (an install for all users shows
Windows' administrator prompt). A copy that is not installed (a
development run) gets the installer saved to Downloads and opened instead. Downloads only ever
come from this repository's release assets.

Updates are found by comparing the app's version (`desktop/package.json`) with the newest tag,
so bump `version` before tagging a release. Versions older than 0.2.1 have no updater; install
the first release that includes it by hand.

For development, `LPRISM_UPDATE_API=http://127.0.0.1:PORT/releases` points the check at a fake
release feed (same JSON shape as the GitHub releases API). `npm test` runs the updater tests.

## Building locally

Requires Node 20+, Python 3.10+ and a built dashboard (`src/loopprism/dashboard/dist`
is committed). The build targets the host architecture.

```bash
# from the repo root: a virtualenv with LoopPrism + PyInstaller
python3 -m venv /tmp/lprism-venv
/tmp/lprism-venv/bin/pip install . pyinstaller

cd desktop
npm ci
PYTHON=/tmp/lprism-venv/bin/python npm run dist   # → release/*.dmg, release/*.zip
```

Other scripts: `npm run sidecar` (just freeze the proxy into `sidecar/dist/`),
`npm run pack` (unpacked `.app` in `release/mac-*/`), and `npm start` (run the
app from source against `sidecar/dist/`; set `LPRISM_SIDECAR` to use another binary).

After changing anything in `src/loopprism`, re-run `npm run sidecar` — the app
embeds a frozen copy, not your working tree.

## Releasing

Push a tag named `desktop-v<version>`:

```bash
git tag desktop-v0.1.0 && git push origin desktop-v0.1.0
```

`.github/workflows/release-desktop.yml` builds arm64 and x64 natively on macOS
runners and x64 on a Windows runner (the sidecar must be frozen per architecture and
per OS), and attaches the `.dmg`, `.zip` and `.exe` files to a GitHub Release. It can also be run manually
(`workflow_dispatch`) to produce artifacts without a release.

Before the Windows installer is attached, the same job installs it and drives the installed app
with `scripts/smoke-windows.ps1` (launch, dashboard, hooks, the in-place update, uninstall), so a tag
cannot publish a Windows build that does not work. The same smoke test runs on pull requests that
touch the desktop app (`.github/workflows/windows-smoke.yml`).

Locally on Windows: `cd desktop && npm ci && npm run dist` (with `PYTHON` pointing at a Python that
has `pip install . pyinstaller`) produces `release/LoopPrism-<version>-x64.exe`.

### Signing and notarization

Without secrets the app is **ad-hoc signed** — a valid signature that Apple
Silicon needs to launch the bundle, but not trusted by Gatekeeper (hence the
first-launch steps above). To ship a trusted build, add these repository secrets;
the workflow and `electron-builder.config.js` pick them up automatically:

| Secret | Value |
| --- | --- |
| `MAC_CERTIFICATE_P12_BASE64` | base64 of the *Developer ID Application* `.p12` |
| `MAC_CERTIFICATE_PASSWORD` | its password |
| `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID` | for notarization |

The sidecar's bundled libraries are signed along with the app. `build/entitlements.mac.plist`
disables library validation so the frozen Python can load them. The signed/notarized path
is untested so far.

## Layout

| Path | Purpose |
| --- | --- |
| `src/main.js` | Electron main: window, tray, lifecycle |
| `src/ui/` | The window: sidebar, Apps and Settings pages (the dashboard is embedded) |
| `src/agents.js`, `src/agent-worker.js` | Detect/connect Claude Code, Codex and WorkBuddy via the bundled `../npm` installers |
| `src/settings.js` | Persisted app settings (ports, login item, onboarding) |
| `src/sidecar.js` | Spawns/supervises the proxy, health checks, restart, cleanup |
| `src/ports.js` | Free-port selection |
| `sidecar/entry.py`, `sidecar/lprism.spec` | PyInstaller entry point and spec |
| `scripts/build-sidecar.js` | Builds the sidecar and smoke-tests it (macOS and Windows) |
| `electron-builder.config.js` | Packaging and signing config |
