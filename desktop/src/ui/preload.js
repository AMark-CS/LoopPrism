const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("lp", {
  state: () => ipcRenderer.invoke("state"),
  agents: () => ipcRenderer.invoke("agents:list"),
  bundleHash: () => ipcRenderer.invoke("hooks:hash"),
  useThisApp: () => ipcRenderer.invoke("hooks:use-app"),
  setAgent: (id, enabled) => ipcRenderer.invoke("agents:set", id, enabled),
  saveSettings: (patch) => ipcRenderer.invoke("settings:save", patch),
  updateState: () => ipcRenderer.invoke("update:state"),
  checkUpdate: () => ipcRenderer.invoke("update:check"),
  installUpdate: () => ipcRenderer.invoke("update:install"),
  onUpdate: (cb) => ipcRenderer.on("update", (_e, s) => cb(s)),
  restartProxy: () => ipcRenderer.invoke("proxy:restart"),
  copy: (text) => ipcRenderer.invoke("copy", text),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  showLogs: () => ipcRenderer.invoke("show-logs"),
  revealData: () => ipcRenderer.invoke("reveal-data"),
  onStatus: (cb) => ipcRenderer.on("status", (_e, s) => cb(s)),
  onNavigate: (cb) => ipcRenderer.on("navigate", (_e, tab) => cb(tab)),
});
