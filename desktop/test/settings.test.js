"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { Settings } = require("../src/settings");

const file = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), "lp-set-")), "sub", "settings.json");

test("the theme defaults to dark and accepts dark, light and system", () => {
  const f = file();
  const s = new Settings(f);
  assert.equal(s.get("theme"), "dark");
  for (const theme of ["light", "system", "dark"]) assert.equal(s.update({ theme }).theme, theme);
});

test("an unknown theme is refused and changes nothing", () => {
  const f = file();
  const s = new Settings(f);
  s.update({ theme: "light" });
  assert.throws(() => s.update({ theme: "sepia" }), /dark, light or system/);
  assert.equal(s.get("theme"), "light");
});

test("settings survive a restart, and older files without a theme read as dark", () => {
  const f = file();
  new Settings(f).update({ theme: "system", proxyPort: 4400 });
  const again = new Settings(f);
  assert.deepEqual([again.get("theme"), again.get("proxyPort")], ["system", 4400]);
  fs.writeFileSync(f, JSON.stringify({ proxyPort: 4317, dashboardPort: 8080 }));
  assert.equal(new Settings(f).get("theme"), "dark");
});

test("a file written mid-way by a crash is not left behind (writes go through a temp file)", () => {
  const f = file();
  new Settings(f).update({ theme: "light" });
  assert.deepEqual(fs.readdirSync(path.dirname(f)), ["settings.json"]);
});

test("the language defaults to system, accepts en and zh, and refuses others", () => {
  const s = new Settings(file());
  assert.equal(s.get("language"), "system");
  for (const language of ["zh", "en", "system"]) assert.equal(s.update({ language }).language, language);
  assert.throws(() => s.update({ language: "fr" }), /Language must be/);
  assert.equal(s.get("language"), "system");
});

test("resolveLang follows the setting, or the OS locale for system", () => {
  const { resolveLang } = require("../src/lang");
  assert.equal(resolveLang("zh", "en-US"), "zh");
  assert.equal(resolveLang("en", "zh-CN"), "en");
  assert.equal(resolveLang("system", "zh-CN"), "zh");
  assert.equal(resolveLang("system", "en-GB"), "en");
});
