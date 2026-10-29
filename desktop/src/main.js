const path = require("node:path");
const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  nativeTheme,
  clipboard,
  ipcMain,
  nativeImage,
  net,
  shell,
} = require("electron");
const agents = require("./agents");
const { Updater } = require("./updater");
const { Settings } = require("./settings");
const { Sidecar } = require("./sidecar");

const isDev = !app.isPackaged;
// Windows has no "opened at login" flag to read back, so the login item passes one.
const HIDDEN_FLAG = "--hidden";
const launchedHidden = () =>
  process.argv.includes(HIDDEN_FLAG) || app.getLoginItemSettings().wasOpenedAtLogin;
const UI = path.join(__dirname, "ui");

function sidecarBinary() {
  if (process.env.LPRISM_SIDECAR) return process.env.LPRISM_SIDECAR;
  const base = isDev
    ? path.join(__dirname, "..", "sidecar", "dist")
    : path.join(process.resourcesPath, "sidecar");
  return path.join(base, "lprism", process.platform === "win32" ? "lprism.exe" : "lprism");
}

if (!app.requestSingleInstanceLock()) {
  // Another instance already owns the sidecar and the ports.
  app.quit();
  process.exit(0);
}

let settings;
let sidecar;
let updater;
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
  // macOS wants a monochrome "template" image that follows the menu bar's
  // light/dark; Windows and Linux trays show a regular colour icon.
  const mac = process.platform === "darwin";
  const img = nativeImage.createFromPath(
    path.join(__dirname, "..", "assets", mac ? "trayTemplate.png" : "tray.png"),
  );
  if (mac) img.setTemplateImage(true);
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
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#0e0e13" : "#f6f6fa",
    ...(process.platform === "darwin"
      ? { titleBarStyle: "hiddenInset", trafficLightPosition: { x: 16, y: 14 } }
      : { autoHideMenuBar: true }),
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
    if ("theme" in patch) nativeTheme.themeSource = values.theme;
    if ("openAtLogin" in patch) {
      app.setLoginItemSettings({ openAtLogin: values.openAtLogin, openAsHidden: true, args: [HIDDEN_FLAG] });
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

  handle("update:state", () => updater.state);
  handle("update:check", () => updater.check({ manual: true }));
  handle("update:install", () => updater.install());

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
  // The Theme setting ("dark" | "light" | "system") drives Electron's nativeTheme: the window's
  // title bar and scrollbars, and `prefers-color-scheme` for the app UI and the embedded dashboard.
  nativeTheme.themeSource = settings.get("theme");
  // Windows and Linux would show a default File/Edit/View menu bar above the UI.
  if (process.platform !== "darwin") Menu.setApplicationMenu(null);
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
  // Windows/Linux trays open the app on a click; macOS shows the menu.
  if (process.platform !== "darwin") tray.on("click", () => showWindow());
  updateTray();
  startUpdater();

  // Safety nets so the sidecar never outlives us.
  process.on("exit", () => sidecar.killNow());
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => app.quit());
  }

  // Show the window straight away (it says "Starting…"); stay hidden when the
  // login item launched us.
  if (!launchedHidden()) createWindow();

  await sidecar.start();
  refreshHooks().catch(() => {});
  if (process.env.LPRISM_TOUR_DIR) runTour(process.env.LPRISM_TOUR_DIR).catch((e) => console.error("tour", e));
});

/**
 * Test hook (LPRISM_TOUR_DIR): visit every page and save a PNG of each, so the UI can be compared
 * across platforms. LPRISM_TOUR_SESSION adds the views of one session.
 */
async function runTour(dir) {
  const fs = require("node:fs");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  fs.mkdirSync(dir, { recursive: true });
  const shot = async (name) => {
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.join(dir, `${process.env.LPRISM_TOUR_PREFIX || ""}${name}.png`), image.toPNG());
    console.log(`tour: ${name} ${image.getSize().width}x${image.getSize().height}`);
  };
  while (status.state !== "running") await wait(250);
  showWindow();
  win.setSize(1280, 820);
  await wait(2500);
  for (const tab of ["sessions", "live", "apps", "settings"]) {
    showWindow(tab);
    await wait(3000);
    await shot(tab);
  }
  const sid = process.env.LPRISM_TOUR_SESSION;
  if (sid) {
    showWindow("sessions");
    for (const view of ["chat", "trajectory", "context", "agents"]) {
      await win.webContents.executeJavaScript(
        `document.querySelector("#dash").src = ${JSON.stringify(`${status.dashboardUrl}/?theme=auto#/sessions/${sid}/${view}`)}`,
      );
      await wait(3000);
      await shot(`session-${view}`);
    }
  }
  win.setSize(900, 640); // a narrow window, to see the responsive layout
  showWindow("sessions");
  await wait(2000);
  await shot("narrow");
  if (process.env.LPRISM_TOUR_QUIT === "1") app.quit();
}

/** Looks for a newer release a few seconds after launch (at most once a day). */
function startUpdater() {
  // What the updater replaces: the .app bundle (<name>.app/Contents/MacOS/<binary>) on
  // macOS; on Windows the installer handles it, so the running exe is enough.
  const bundle = !app.isPackaged
    ? null
    : process.platform === "win32"
      ? process.execPath
      : path.resolve(process.execPath, "..", "..", "..");
  const override = process.env.LPRISM_UPDATE_API; // tests / development: a fake release feed
  updater = new Updater({
    current: app.getVersion(),
    arch: process.arch,
    platform: process.platform,
    bundle,
    tmpDir: app.getPath("temp"),
    downloadsDir: app.getPath("downloads"),
    pid: process.pid,
    cache: { load: () => settings.get("updateCache"), save: (c) => settings.update({ updateCache: c }) },
    fetchImpl: (url, opts) => net.fetch(url, opts),
    openPath: (p) => shell.openPath(p),
    openExternal: (u) => shell.openExternal(u),
    quit: () => app.quit(),
    ...(override ? { apiUrl: override, trusted: (u) => u.startsWith(new URL(override).origin) } : {}),
  });
  updater.on("state", (s) => win?.webContents.send("update", s));
  updater.restore(); // the button shows from the last answer straight away
  // GitHub is asked at most once a day; the hourly tick only retries a check that failed
  // (offline, rate limit) or runs when a day has passed in a long-running app.
  setTimeout(() => updater.checkIfDue(), 8000);
  // End-to-end test hook (only with the fake feed above): fetch and install whatever it offers.
  if (override && process.env.LPRISM_UPDATE_AUTOINSTALL === "1") {
    setTimeout(async () => {
      await updater.check({ manual: true });
      await updater.install();
    }, 10_000);
  }
  setInterval(() => updater.checkIfDue(), 60 * 60 * 1000);
}

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

// Closing the window keeps the proxy running in the menu bar / system tray.
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
