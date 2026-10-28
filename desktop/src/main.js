const path = require("node:path");
const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  clipboard,
  nativeImage,
  shell,
} = require("electron");
const { Sidecar } = require("./sidecar");

const isDev = !app.isPackaged;

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
  const proxyHost = status.proxyUrl?.replace("http://", "");
  tray.setToolTip(
    running
      ? `LoopPrism — proxy on ${proxyHost}`
      : `LoopPrism — ${STATUS_LABEL[status.state]}`,
  );
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: `LoopPrism: ${STATUS_LABEL[status.state]}`, enabled: false },
      ...(status.proxyUrl
        ? [{ label: `Proxy ${status.proxyUrl}`, enabled: false }]
        : []),
      { type: "separator" },
      {
        label: "Open dashboard",
        enabled: running,
        click: showWindow,
      },
      {
        label: "Copy proxy URL",
        enabled: Boolean(status.proxyUrl),
        click: () => clipboard.writeText(status.proxyUrl),
      },
      { type: "separator" },
      {
        label: "Restart proxy",
        click: () => sidecar.restart(),
      },
      {
        label: "Show logs",
        click: () => shell.openPath(sidecar.logFile),
      },
      { type: "separator" },
      { label: "Quit LoopPrism", click: () => app.quit() },
    ]),
  );
}

function errorPage(message) {
  const html = `<body style="font:14px -apple-system,sans-serif;background:#0b1437;color:#dfe6ff;padding:48px">
    <h2>LoopPrism proxy is not running</h2>
    <p>${message.replace(/[<>&]/g, "")}</p>
    <p>Use the menu bar icon → <b>Restart proxy</b>, or <b>Show logs</b> for details.</p></body>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 720,
    minHeight: 480,
    title: "LoopPrism",
    backgroundColor: "#0b1437",
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  win.setTitle("LoopPrism");
  win.on("closed", () => {
    win = null;
  });
  // Links out of the dashboard open in the user's browser, not in-app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (status.dashboardUrl && !url.startsWith(status.dashboardUrl)) {
      event.preventDefault();
      if (/^https?:/.test(url)) shell.openExternal(url);
    }
  });
  loadDashboard();
}

function loadDashboard() {
  if (!win) return;
  if (status.state === "running") win.loadURL(status.dashboardUrl);
  else if (status.state === "failed") {
    win.loadURL(errorPage("The bundled proxy keeps crashing."));
  }
}

function showWindow() {
  if (!win) createWindow();
  else {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }
}

let shownUrl = null;
function onStatus(next) {
  status = next;
  updateTray();
  if (next.state === "running") {
    // Show the window on first start; after a restart, reload it only if the
    // dashboard moved to a different port or the page died with the process.
    if (!win && shownUrl === null) createWindow();
    else if (win && shownUrl !== next.dashboardUrl) win.loadURL(next.dashboardUrl);
    else if (win) win.webContents.reload();
    shownUrl = next.dashboardUrl;
  } else if (next.state === "failed") {
    if (!win) createWindow();
    else loadDashboard();
  }
}

app.on("second-instance", () => {
  if (status.state === "running") showWindow();
});

app.whenReady().then(async () => {
  const logDir = app.getPath("logs");
  sidecar = new Sidecar({
    binary: sidecarBinary(),
    logFile: path.join(logDir, "sidecar.log"),
    pidFile: path.join(app.getPath("userData"), "sidecar.pid"),
  });
  sidecar.on("status", onStatus);

  tray = new Tray(trayIcon());
  updateTray();

  // Safety nets so the sidecar never outlives us.
  process.on("exit", () => sidecar.killNow());
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => app.quit());
  }

  await sidecar.start();
});

// Closing the window keeps the proxy running in the menu bar.
app.on("window-all-closed", () => {});

app.on("activate", () => {
  if (status.state === "running" || status.state === "failed") showWindow();
});

app.on("before-quit", (event) => {
  if (quitting) return;
  quitting = true;
  event.preventDefault();
  sidecar
    .stop()
    .catch(() => sidecar.killNow())
    .finally(() => app.exit(0));
});
