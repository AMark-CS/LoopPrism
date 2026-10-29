const t = (text, vars) => I18N.t(text, vars);
const $ = (sel) => document.querySelector(sel);
const el = (tag, props = {}, ...kids) => {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids) node.append(k);
  return node;
};

let state = null;
let agents = [];
let hooks = { matches: true };
let dashboardUrl = null;
let toastTimer;

function toast(text) {
  const box = $("#toast");
  box.textContent = t(text);
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 2500);
}

/* ---------- tabs ---------- */
const DASH_TABS = new Set(["sessions", "cost", "optimize"]);
let route = "sessions";
let applied = null; // route currently loaded in the iframe (keeps inner navigation when switching tabs)

function dashSrc() {
  // theme=auto: the dashboard follows the window's light/dark (set by the Theme setting); lang: the Language setting.
  return `${dashboardUrl}/?theme=auto&lang=${I18N.lang}#/${route}`;
}

function showTab(name) {
  if (name === "dashboard") name = "sessions";
  if (DASH_TABS.has(name)) {
    route = name;
    if (dashboardUrl && applied !== name) {
      applied = name;
      $("#dash").src = dashSrc();
    }
  }
  const pane = DASH_TABS.has(name) ? "dashboard" : name;
  for (const b of document.querySelectorAll("nav button")) {
    b.classList.toggle("active", b.dataset.tab === name);
  }
  for (const t of document.querySelectorAll(".tab")) {
    t.classList.toggle("active", t.id === `tab-${pane}`);
  }
  if (name === "apps") refreshAgents();
  if (name === "settings") fillSettings();
}
for (const b of document.querySelectorAll("nav button")) {
  b.onclick = () => showTab(b.dataset.tab);
}
lp.onNavigate(showTab);

/* ---------- proxy status ---------- */
const LABEL = {
  starting: "Starting…",
  running: "Proxy running",
  restarting: "Restarting…",
  failed: "Proxy stopped",
  stopped: "Stopped",
};

function applyStatus(s) {
  state = { ...state, status: s };
  $("#dot").className = `dot ${s.state}`;
  $("#state-text").textContent =
    s.state === "running" && s.external ? t("Using running proxy") : t(LABEL[s.state] || s.state);
  $("#copy-proxy").disabled = !s.proxyUrl;

  const overlay = $("#overlay");
  const dash = $("#dash");
  if (s.state === "running") {
    dashboardUrl = s.dashboardUrl; // also reloads after a proxy restart
    applied = route;
    dash.src = dashSrc();
    overlay.classList.add("hidden");
  } else {
    overlay.classList.remove("hidden");
    $("#overlay-text").textContent = t(
      s.state === "failed"
        ? "The bundled proxy keeps crashing. Open the proxy log from Settings, then restart it from the tray icon."
        : "Starting the LoopPrism proxy…",
    );
  }
  updateMcpOut();
}
lp.onStatus(applyStatus);
$("#copy-proxy").onclick = async () => {
  await lp.copy(state.status.proxyUrl);
  toast("Proxy URL copied");
};

/* ---------- apps ---------- */
function ago(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return t("just now");
  if (s < 3600) return t("{n} min ago", { n: Math.floor(s / 60) });
  if (s < 86400) return t("{n} h ago", { n: Math.floor(s / 3600) });
  return t("{n} d ago", { n: Math.floor(s / 86400) });
}

function renderAgents() {
  const list = $("#agent-list");
  list.replaceChildren();
  if (!agents.length) {
    list.append(el("div", { className: "card", textContent: t("Checking for installed apps…") }));
  }
  for (const a of agents) {
    const toggle = el("input", { type: "checkbox", className: "switch" });
    toggle.checked = a.connected;
    toggle.disabled = a.busy || !a.canToggle;
    toggle.onchange = () => setAgent(a, toggle.checked);

    const pill = a.readOnly
      ? el("span", { className: "pill", textContent: t("Read from disk") })
      : a.busy
      ? el("span", { className: "pill", textContent: t("Working…") })
      : a.connected
        ? el("span", {
            className: "pill on",
            textContent: a.lastSeen ? `${t("Monitoring")} · ${ago(a.lastSeen)}` : t("Monitoring"),
          })
        : a.found
          ? el("span", { className: "pill", textContent: t("Not monitored") })
          : el("span", { className: "pill warn", textContent: t("Not found") });

    const info = el(
      "div",
      { className: "info" },
      el("div", { className: "title" }, a.name, pill),
      el("div", { className: "desc", textContent: t(a.blurb) }),
      el("div", { className: "sessions-count", textContent: t("{n} sessions", { n: a.sessions ?? 0 }) }),
    );
    if (a.error) info.append(el("div", { className: "note err", textContent: a.error }));
    else if (a.connected && !hooks.matches) {
      const fix = el("button", { className: "ghost", textContent: t("Send to this app") });
      fix.onclick = async () => {
        await lp.useThisApp();
        await refreshAgents();
      };
      info.append(
        el(
          "div",
          { className: "note err" },
          t("Its hooks send events to {url}, not to this app ({app}). ", { url: hooks.url, app: state.status.dashboardUrl }),
          fix,
        ),
      );
    }
    else if (a.hint) info.append(el("div", { className: "note", textContent: t(a.hint) }));

    list.append(el("div", { className: "card agent" }, ...(a.readOnly ? [info] : [info, toggle])));
  }
}

async function refreshAgents() {
  const res = await lp.agents();
  if (res.error) {
    agents = [];
    toast(res.error);
    return;
  }
  // keep per-card transient hints/busy flags across refreshes
  const old = Object.fromEntries(agents.map((a) => [a.id, a]));
  hooks = res.hooks || { matches: true };
  agents = res.agents.map((a) => ({ ...a, hint: old[a.id]?.connected === a.connected ? old[a.id]?.hint : undefined }));
  renderAgents();
}

async function setAgent(a, enabled) {
  a.busy = true;
  a.error = undefined;
  renderAgents();
  const res = await lp.setAgent(a.id, enabled);
  a.busy = false;
  if (res.error) {
    a.error = res.error;
    a.connected = !enabled;
    renderAgents();
    return;
  }
  await refreshAgents();
  const fresh = agents.find((x) => x.id === a.id);
  if (fresh && enabled) fresh.hint = a.afterConnect;
  renderAgents();
}

$("#welcome-ok").onclick = () => {
  $("#welcome").hidden = true;
};

/** First launch: connect every detected app so it works straight away. */
async function autoSetup() {
  const todo = agents.filter((x) => x.found && !x.connected && x.canToggle);
  if (!todo.length) return;
  showTab("apps");
  for (const a of todo) await setAgent(a, true);
  if (agents.some((a) => a.connected)) {
    await lp.saveSettings({ onboarded: true, hooksHash: await lp.bundleHash() });
    state.settings.onboarded = true;
    $("#welcome").hidden = false;
  }
}
setInterval(() => {
  if ($("#tab-apps").classList.contains("active")) refreshAgents();
}, 8000);

// "Choose apps to monitor" button in the embedded dashboard's empty state.
window.addEventListener("message", (e) => {
  if (e.source === $("#dash").contentWindow && e.data?.type === "loopprism:open-apps") {
    showTab("apps");
  }
});

/* ---------- other MCP clients ---------- */
function updateMcpOut() {
  const name = $("#mcp-name").value.trim().replace(/[^\w.-]/g, "-") || "<name>";
  const url = $("#mcp-url").value.trim();
  const base = state?.status?.proxyUrl || "http://127.0.0.1:4317";
  $("#mcp-out").textContent = `${base}/${name}${url ? `?backend=${encodeURIComponent(url)}` : "?backend=<server url>"}`;
}
$("#mcp-name").oninput = updateMcpOut;
$("#mcp-url").oninput = updateMcpOut;
$("#mcp-copy").onclick = async () => {
  await lp.copy($("#mcp-out").textContent);
  toast("Copied");
};

/* ---------- settings ---------- */
function fillSettings() {
  const s = state.settings;
  $("#port-proxy").value = s.proxyPort;
  $("#port-dash").value = s.dashboardPort;
  $("#login").checked = s.openAtLogin;
  for (const r of document.querySelectorAll('input[name="language"]')) r.checked = r.value === (s.language || "system");
  for (const r of document.querySelectorAll('input[name="theme"]')) r.checked = r.value === (s.theme || "dark");
  $("#db-path").textContent = state.dbPath;
  $("#version").textContent = `LoopPrism ${state.version}`;
  const st = state.status;
  const moved = st.proxyUrl && (!st.proxyUrl.endsWith(`:${s.proxyPort}`) || !st.dashboardUrl.endsWith(`:${s.dashboardPort}`));
  $("#port-note").textContent = moved
    ? t("Those ports were busy, so the app is using {proxy} and {dash} right now.", { proxy: st.proxyUrl, dash: st.dashboardUrl })
    : t("If a port is busy the app picks a free one automatically.");
}
$("#save-ports").onclick = async () => {
  const msg = $("#port-msg");
  msg.className = "msg";
  msg.textContent = t("Restarting…");
  const res = await lp.saveSettings({
    proxyPort: Number($("#port-proxy").value),
    dashboardPort: Number($("#port-dash").value),
  });
  if (res.error) {
    msg.className = "msg bad";
    msg.textContent = res.error;
    return;
  }
  state.settings = res.settings;
  msg.textContent = t("Applied");
  setTimeout(fillSettings, 800);
};
for (const r of document.querySelectorAll('input[name="theme"]')) {
  r.onchange = async () => {
    const res = await lp.saveSettings({ theme: r.value });
    if (res.error) toast(res.error);
  };
}
for (const r of document.querySelectorAll('input[name="language"]')) {
  r.onchange = async () => {
    const res = await lp.saveSettings({ language: r.value });
    if (res.error) return toast(res.error);
    state.settings = res.settings;
    applyLanguage();
  };
}
$("#login").onchange = async (e) => {
  const res = await lp.saveSettings({ openAtLogin: e.target.checked });
  if (!res.error) state.settings = res.settings;
};
document.body.classList.add(`os-${lp.platform}`);
if (lp.platform !== "darwin") {
  $("#reveal").textContent = "Show in Explorer";
  for (const el of document.querySelectorAll("[data-mac]")) el.textContent = el.dataset.win ?? el.textContent;
}

/** Translate the window and reload the dashboard in the chosen language. */
function applyLanguage() {
  I18N.setLang(state.settings.language);
  if (state.status) applyStatus(state.status);
  renderAgents();
  if (state.updateInfo) applyUpdate(state.updateInfo);
  fillSettings();
}
$("#open-optimize").onclick = () => showTab("optimize");
$("#reveal").onclick = () => lp.revealData();
$("#logs").onclick = () => lp.showLogs();
$("#browser").onclick = () => state.status.dashboardUrl && lp.openExternal(state.status.dashboardUrl);

/* ---------- updates ---------- */
// The button only exists while a newer version is available (or being installed).
function applyUpdate(u) {
  state = { ...state, updateInfo: u };
  const box = $("#update-box");
  const busy = u.phase === "downloading" || u.phase === "installing";
  const show = ["available", "downloading", "installing", "downloaded", "error"].includes(u.phase) && u.latest;
  box.hidden = !show;
  const btn = $("#update-btn");
  const sub = $("#update-sub");
  const bar = $("#update-bar");
  btn.disabled = busy;
  bar.hidden = u.phase !== "downloading";
  $("#update-fill").style.width = `${u.percent ?? 0}%`;
  sub.className = `update-sub${u.phase === "error" ? " bad" : ""}`;
  const label = {
    available: t("Update to {v}", { v: u.latest }),
    downloading: t("Downloading… {p}%", { p: u.percent ?? 0 }),
    installing: "Installing…",
    downloaded: "Open installer",
    error: "Try again",
  }[u.phase];
  if (label) $("#update-label").textContent = t(label);
  sub.textContent =
    u.phase === "error"
      ? u.error
      : u.phase === "downloaded"
        ? t(lp.platform === "win32" ? "Run the installer to finish." : "Drag LoopPrism into Applications to finish.")
        : u.phase === "installing"
          ? t("LoopPrism will restart.")
          : t("You have {v}.", { v: u.current });
  const msg = $("#update-msg");
  if (u.checked) {
    msg.className = `msg${u.error && u.phase !== "error" ? " bad" : ""}`;
    msg.textContent = u.error && u.phase !== "error"
      ? u.error
      : u.phase === "idle"
        ? t("You're on the latest version ({v}).", { v: u.current })
        : t("Version {v} is available.", { v: u.latest });
  }
}
lp.onUpdate(applyUpdate);
$("#update-btn").onclick = () => lp.installUpdate();
$("#check-update").onclick = async () => {
  $("#update-msg").className = "msg";
  $("#update-msg").textContent = t("Checking…");
  applyUpdate(await lp.checkUpdate());
};

/* ---------- boot ---------- */
(async () => {
  state = await lp.state();
  I18N.setLang(state.settings.language);
  applyStatus(state.status);
  applyUpdate(await lp.updateState());
  await refreshAgents();
  if (!state.settings.onboarded) await autoSetup();
})();
