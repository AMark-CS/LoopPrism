/* Interface language of the window. English text is the key; a string with no entry stays English.
   Static HTML is translated in place (originals are kept so switching back works); dynamic text uses t(). */
(() => {
  const ZH = {
    Sessions: "会话",
    Cost: "成本",
    Optimize: "优化",
    Apps: "应用",
    Settings: "设置",
    "Starting…": "正在启动…",
    "Proxy running": "代理运行中",
    "Using running proxy": "使用已运行的代理",
    "Restarting…": "正在重启…",
    "Proxy stopped": "代理已停止",
    Stopped: "已停止",
    "Copy proxy URL": "复制代理地址",
    "Proxy URL copied": "已复制代理地址",
    Copied: "已复制",
    Update: "更新",
    "Starting the LoopPrism proxy…": "正在启动 LoopPrism 代理…",
    "The bundled proxy keeps crashing. Open the proxy log from Settings, then restart it from the tray icon.":
      "内置代理反复崩溃。请在设置中打开代理日志,然后从托盘图标重启它。",
    "Choose which coding agents LoopPrism records. Each one is connected with a small hook that sends prompts, tool calls and errors to this app. Nothing leaves your machine.":
      "选择 LoopPrism 要记录哪些编码智能体。每个应用通过一个小钩子把提示词、工具调用和错误发送到本应用,数据不会离开你的电脑。",
    "You're all set": "已就绪",
    "LoopPrism turned on monitoring for the apps it found on this Mac. Switch off any you don't want.":
      "LoopPrism 已为在这台 Mac 上找到的应用开启监控,不需要的可以关掉。",
    "LoopPrism turned on monitoring for the apps it found on this PC. Switch off any you don't want.":
      "LoopPrism 已为在这台电脑上找到的应用开启监控,不需要的可以关掉。",
    "Got it": "知道了",
    "Claude Code, Codex, WorkBuddy, DeepSeek Harness and OpenCode sessions are also read from disk, with nothing to set up, and appear under Sessions. DeepSeek Harness has no live-run hook yet.":
      "Claude Code、Codex、WorkBuddy、DeepSeek Harness 和 OpenCode 的会话也会直接从磁盘读取,无需设置,显示在“会话”中。DeepSeek Harness 暂无实时钩子。",
    "Other MCP clients": "其他 MCP 客户端",
    "Any client that talks to MCP servers over HTTP can be recorded by pointing it at the proxy instead of the server.":
      "任何通过 HTTP 连接 MCP 服务器的客户端,只要指向代理而不是服务器,就能被记录。",
    Name: "名称",
    "Server URL": "服务器地址",
    "Use this URL in your client": "在客户端中使用此地址",
    Copy: "复制",
    Ports: "端口",
    Proxy: "代理",
    Dashboard: "仪表盘",
    "Apply and restart proxy": "应用并重启代理",
    Applied: "已应用",
    Appearance: "外观",
    Dark: "深色",
    Light: "浅色",
    System: "跟随系统",
    "System follows your operating system's light or dark setting.": "“跟随系统”会使用操作系统的浅色或深色设置。",
    Language: "语言",
    "Interface language. System follows your operating system.": "界面语言。“跟随系统”会使用操作系统的语言。",
    "Suggestions for spending less. Tool lookup on GitHub and the optional AI analysis (your own model URL and API key) are set on the Optimize page.":
      "帮你少花钱的建议。GitHub 工具查找和可选的 AI 分析(使用你自己的模型地址和 API 密钥)在“优化”页面设置。",
    "Open Optimize settings": "打开优化设置",
    General: "通用",
    "Open LoopPrism at login": "登录时打开 LoopPrism",
    "Keeps the proxy running in the menu bar.": "让代理在菜单栏中持续运行。",
    "Keeps the proxy running in the system tray.": "让代理在系统托盘中持续运行。",
    Data: "数据",
    "Show in Finder": "在访达中显示",
    "Show in Explorer": "在资源管理器中显示",
    "Open proxy log": "打开代理日志",
    "Open dashboard in browser": "在浏览器中打开仪表盘",
    Updates: "更新",
    "Check for updates": "检查更新",
    "If a port is busy the app picks a free one automatically.": "如果端口被占用,应用会自动选择空闲端口。",
    "Checking for installed apps…": "正在检查已安装的应用…",
    "Working…": "处理中…",
    Monitoring: "监控中",
    "Not monitored": "未监控",
    "Not found": "未找到",
    "Send to this app": "发送到本应用",
    "just now": "刚刚",
    "{n} min ago": "{n} 分钟前",
    "{n} h ago": "{n} 小时前",
    "{n} d ago": "{n} 天前",
    "Its hooks send events to {url}, not to this app ({app}). ": "它的钩子把事件发送到 {url},而不是本应用({app})。",
    "Those ports were busy, so the app is using {proxy} and {dash} right now.": "这些端口被占用,应用目前使用 {proxy} 和 {dash}。",
    "Update to {v}": "更新到 {v}",
    "Downloading… {p}%": "下载中… {p}%",
    "You have {v}.": "当前版本 {v}。",
    "You're on the latest version ({v}).": "已是最新版本({v})。",
    "Version {v} is available.": "有新版本 {v} 可用。",
    English: "English",
    "Checking…": "检查中…",
    "Installing…": "正在安装…",
    "Open installer": "打开安装程序",
    "Try again": "重试",
    "Run the installer to finish.": "运行安装程序以完成更新。",
    "Drag LoopPrism into Applications to finish.": "把 LoopPrism 拖进“应用程序”以完成更新。",
    "LoopPrism will restart.": "LoopPrism 将重新启动。",
    // Agent cards (text comes from the main process)
    "Records every prompt, tool call and error as a run. Installs the LoopPrism plugin through the claude CLI.":
      "把每条提示词、工具调用和错误记录为一次运行。通过 claude 命令行安装 LoopPrism 插件。",
    "Records every prompt and tool call as a run. Adds hooks to ~/.workbuddy/settings.json.":
      "把每条提示词和工具调用记录为一次运行。会在 ~/.workbuddy/settings.json 中添加钩子。",
    "Records every prompt, tool call and error as a run. Adds hooks to ~/.codex/hooks.json.":
      "把每条提示词、工具调用和错误记录为一次运行。会在 ~/.codex/hooks.json 中添加钩子。",
    "Restart running Claude Code sessions to start recording.": "重启正在运行的 Claude Code 会话以开始记录。",
    "Restart WorkBuddy so it picks up the hooks.": "重启 WorkBuddy 以加载钩子。",
    "Open Codex and run /hooks once to review and trust the LoopPrism hooks.":
      "打开 Codex 并运行一次 /hooks,以审查并信任 LoopPrism 的钩子。",
  };

  const ATTRS = ["placeholder", "aria-label", "title"];
  const originals = new WeakMap(); // node or element -> its English text
  let lang = "en";

  function resolve(setting) {
    if (setting === "en" || setting === "zh") return setting;
    return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
  }

  function t(text, vars) {
    let out = lang === "zh" ? ZH[text] ?? text : text;
    if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
    return out;
  }

  function walk(root) {
    const it = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = it.nextNode(); n; n = it.nextNode()) {
      if (n.parentElement?.closest("script, style, code")) continue;
      const en = originals.get(n) ?? n.nodeValue;
      const key = en.trim();
      if (!key || !(key in ZH)) continue;
      originals.set(n, en);
      n.nodeValue = lang === "zh" ? en.replace(key, ZH[key]) : en;
    }
    for (const e of root.querySelectorAll("[placeholder], [aria-label], [title]")) {
      for (const a of ATTRS) {
        if (!e.hasAttribute(a)) continue;
        const saved = originals.get(e) ?? {};
        const en = saved[a] ?? e.getAttribute(a);
        if (!(en in ZH)) continue;
        saved[a] = en;
        originals.set(e, saved);
        e.setAttribute(a, lang === "zh" ? ZH[en] : en);
      }
    }
  }

  function setLang(setting) {
    lang = resolve(setting);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    walk(document.body);
  }

  window.I18N = { t, setLang, apply: () => walk(document.body), get lang() { return lang; } };
})();
