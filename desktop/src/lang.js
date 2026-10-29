/** Interface language of the app shell: the Language setting ("system" | "en" | "zh") resolved to en or zh. */
function resolveLang(setting, locale) {
  if (setting === "en" || setting === "zh") return setting;
  return String(locale || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

// Tray menu text (the window itself is translated in ui/i18n.js).
const TRAY_ZH = {
  "Starting…": "正在启动…",
  Running: "运行中",
  "Restarting…": "正在重启…",
  "Stopped (crashed)": "已停止(崩溃)",
  Stopped: "已停止",
  "(existing proxy)": "(已有代理)",
  Sessions: "会话",
  Cost: "成本",
  Optimize: "优化",
  "Apps…": "应用…",
  "Copy proxy URL": "复制代理地址",
  "Restart proxy": "重启代理",
  "Show logs": "查看日志",
  "Quit LoopPrism": "退出 LoopPrism",
  Proxy: "代理",
  "proxy on": "代理端口",
};

const trayText = (lang, text) => (lang === "zh" ? TRAY_ZH[text] ?? text : text);

module.exports = { resolveLang, trayText };
