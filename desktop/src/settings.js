const fs = require("node:fs");
const path = require("node:path");
const { atomicWrite } = require("./fsutil");

const DEFAULTS = {
  proxyPort: 4317,
  dashboardPort: 8080,
  openAtLogin: false,
  onboarded: false,
  hooksHash: "", // bundled hook scripts last installed by this app
  updateCache: null, // result of the last update check: { at, info }
};

const validPort = (n) => Number.isInteger(n) && n >= 1024 && n <= 65535;

class Settings {
  constructor(file) {
    this.file = file;
    this.values = { ...DEFAULTS };
    try {
      Object.assign(this.values, JSON.parse(fs.readFileSync(file, "utf8")));
    } catch {
      /* first run */
    }
  }

  get(key) {
    return this.values[key];
  }

  all() {
    return { ...this.values };
  }

  /** Apply a partial update; throws on invalid values. */
  update(patch) {
    const next = { ...this.values };
    for (const key of Object.keys(DEFAULTS)) {
      if (key in patch) next[key] = patch[key];
    }
    if (!validPort(next.proxyPort) || !validPort(next.dashboardPort)) {
      throw new Error("Ports must be numbers between 1024 and 65535.");
    }
    if (next.proxyPort === next.dashboardPort) {
      throw new Error("Proxy and dashboard need different ports.");
    }
    this.values = next;
    atomicWrite(this.file, JSON.stringify(next, null, 2));
    return this.all();
  }
}

module.exports = { Settings };
