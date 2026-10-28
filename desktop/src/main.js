const path = require("node:path");
const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  clipboard,
  ipcMain,
  nativeImage,
  shell,
} = require("electron");
const agents = require("./agents");
const { Settings } = require("./settings");
const { Sidecar } = require("./sidecar");

const isDev = !app.isPackaged;
const UI = path.join(__dirname, "ui");

function sidecarBinary() {
  if (process.env.LPRISM_SIDECAR) return process.env.LPRISM_SIDECAR;
  const base = isDev
    ? path.join(__dirname, "..", "sidecar", "dist")
    : path.join(process.resourcesPath, "sidecar");
  return path.join(base, "lprism", "lprism");
}

if (!app.requestSingleInstanceLock()) {
  // Another instance already owns the sidecar and the ports.
  app.quit();
  process.exit(0);
}

let settings;
let sidecar;
let tray;
let win = null;
let status = { state: "starting", proxyUrl: null, dashboardUrl: null };
let quitting = false;

const STATUS_LABEL = {
  starting: "Starting…",
  running: "Running",
  restarting: "Restarting…",
  failed: "Stopped (crashed)",
  stopped: "Stopped",
};

function trayIcon() {
  const img = nativeImage.createFromPath(
    path.join(__dirname, "..", "assets", "trayTemplate.png"),
  );
  img.setTemplateImage(true);
  return img;
}

function updateTray() {
  if (!tray) return;
  const running = status.state === "running";
  tray.setToolTip(
    running
      ? `LoopPrism — proxy on ${status.proxyUrl.replace("http://", "")}`
      : `LoopPrism — ${STATUS_LABEL[status.state]}`,
  );
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: `LoopPrism: ${STATUS_LABEL[status.state]}${status.external ? " (existing proxy)" : ""}`,
        enabled: false,
      },
      ...(status.proxyUrl
        ? [{ label: `Proxy ${status.proxyUrl}`, enabled: false }]
        : []),
      { type: "separator" },
      { label: "Sessions", click: () => showWindow("sessions") },
      { label: "Live runs", click: () => showWindow("live") },
      { label: "Apps…", click: () => showWindow("apps") },
      {
        label: "Copy proxy URL",
        enabled: Boolean(status.proxyUrl),
        click: () => clipboard.writeText(status.proxyUrl),
      },
      { type: "separator" },
      { label: "Restart proxy", click: () => sidecar.restart() },
      { label: "Show logs", click: () => shell.openPath(sidecar.logFile) },
      { type: "separator" },
      { label: "Quit LoopPrism", click: () => app.quit() },
    ]),
  );
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 820,
    minHeight: 520,
    title: "LoopPrism",
    backgroundColor: "#0e0e13",
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 14 },
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      preload: path.join(UI, "preload.js"),
    },
  });
  win.on("closed", () => {
    win = null;
  });
  // Links out of the dashboard open in the user's browser, not in-app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("file:")) event.preventDefault();
  });
  win.loadFile(path.join(UI, "index.html"));
  return win;
}

function showWindow(tab) {
  const fresh = !win;
  if (fresh) createWindow();
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (tab) {
    const send = () => win?.webContents.send("navigate", tab);
    if (fresh) win.webContents.once("did-finish-load", send);
    else send();
  }
}

function onStatus(next) {
  status = next;
  updateTray();
  win?.webContents.send("status", status);
  if (next.state === "running") {
    try {
      agents.syncHookUrl(next.dashboardUrl);
    } catch {
      /* best effort */
    }
  }
}

/* ---------- IPC (only from our own UI) ---------- */
function handle(channel, fn) {
  ipcMain.handle(channel, async (event, ...args) => {
    if (!event.senderFrame.url.startsWith("file:")) {
      throw new Error("forbidden");
    }
    try {
      return await fn(...args);
    } catch (err) {
      return { error: err.message };
    }
  });
}

function dbPath() {
  return (
    process.env.LOOPPRISM_DB_PATH ||
    path.join(app.getPath("home"), ".loopprism", "traces.db")
  );
}

function registerIpc() {
  handle("state", () => ({
    status,
    settings: settings.all(),
    version: app.getVersion(),
    dbPath: dbPath(),
  }));

  handle("agents:list", async () => {
    const [st, seen] = await Promise.all([
      agents.status(),
      agents.lastSeen(status.dashboardUrl),
    ]);
    if (st.error) return { error: st.error };
    return {
      hooks: agents.hookTarget(status.dashboardUrl),
      agents: agents.AGENTS.map((a) => {
        const s = st[a.id] || {};
        const noCli = a.id === "claude" && s.found && !s.cli;
        return {
          ...a,
          found: Boolean(s.found),
          connected: Boolean(s.connected),
          canToggle: s.connected || (s.found && !noCli),
          lastSeen: seen[a.id] || null,
          error: s.error || (noCli ? "The claude command was not found, so the plugin can't be installed from here." : undefined),
        };
      }),
    };
  });

  handle("hooks:hash", () => agents.bundleHash());

  handle("hooks:use-app", () => {
    agents.pointHooksHere(status.dashboardUrl);
    return { ok: true };
  });

  handle("agents:set", (id, enabled) =>
    enabled ? agents.connect(id) : agents.disconnect(id),
  );

  handle("settings:save", async (patch) => {
    const before = settings.all();
    const values = settings.update(patch);
    if ("openAtLogin" in patch) {
      app.setLoginItemSettings({ openAtLogin: values.openAtLogin, openAsHidden: true });
    }
    if (
      values.proxyPort !== before.proxyPort ||
      values.dashboardPort !== before.dashboardPort
    ) {
      sidecar.setPreferred({
        proxy: values.proxyPort,
        dashboard: values.dashboardPort,
      });
    }
    return { settings: values };
  });

  handle("proxy:restart", () => sidecar.restart());
  handle("copy", (text) => clipboard.writeText(String(text)));
  handle("open-external", (url) => {
    if (/^https?:\/\/(127\.0\.0\.1|localhost)[:/]/.test(url)) shell.openExternal(url);
  });
  handle("show-logs", () => shell.openPath(sidecar.logFile));
  handle("reveal-data", () => shell.showItemInFolder(dbPath()));
}

app.on("second-instance", () => showWindow());

app.whenReady().then(async () => {
  settings = new Settings(path.join(app.getPath("userData"), "settings.json"));
  sidecar = new Sidecar({
    binary: sidecarBinary(),
    logFile: path.join(app.getPath("logs"), "sidecar.log"),
    pidFile: path.join(app.getPath("userData"), "sidecar.pid"),
    preferred: {
      proxy: settings.get("proxyPort"),
      dashboard: settings.get("dashboardPort"),
    },
  });
  sidecar.on("status", onStatus);
  registerIpc();

  tray = new Tray(trayIcon());
  updateTray();

  // Safety nets so the sidecar never outlives us.
  process.on("exit", () => sidecar.killNow());
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => app.quit());
  }

  // Show the window straight away (it says "Starting…"); stay hidden when the
  // login item launched us.
  if (!app.getLoginItemSettings().wasOpenedAtLogin) createWindow();

  await sidecar.start();
  refreshHooks().catch(() => {});
});

/**
 * An app update can ship newer hook scripts than the copies installed in
 * Claude Code / Codex. Reinstall for the apps that are already connected so the
 * app and its hooks never drift apart.
 */
async function refreshHooks() {
  const hash = agents.bundleHash();
  if (settings.get("hooksHash") === hash) return;
  const st = await agents.status();
  for (const a of agents.AGENTS) {
    if (st[a.id]?.connected) await agents.connect(a.id);
  }
  settings.update({ hooksHash: hash });
}

// Closing the window keeps the proxy running in the menu bar.
app.on("window-all-closed", () => {});
app.on("activate", () => showWindow());

app.on("before-quit", (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault();
  try {
    agents.syncHookUrl(null);
  } catch {
    /* best effort */
  }
  sidecar
    .stop()
    .catch(() => sidecar.killNow())
    .finally(() => app.exit(0));
});
