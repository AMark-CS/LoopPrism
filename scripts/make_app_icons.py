"""Generate the app tiles shown in the README (docs/assets/apps/*.svg): a rounded grey tile with a
coloured monogram. They are our own drawings, not the apps' logos; replace a file with the real logo
(same name, 96x96) to use that instead."""

from pathlib import Path

APPS = {
    "claude-code": ("CC", "#D97757"),
    "codex": ("Cx", "#4F7CF7"),
    "gemini-cli": ("G", "#4285F4"),
    "opencode": ("oc", "#1F2937"),
    "deepseek-harness": ("DS", "#4D6BFE"),
    "workbuddy": ("WB", "#7C5CFC"),
    "more": ("+", "#9CA3AF"),
}

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
  <rect width="96" height="96" rx="22" fill="#F3F4F6"/>
  <text x="48" y="48" text-anchor="middle" dominant-baseline="central"
        font-family="-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif" font-size="{size}" font-weight="700"
        fill="{color}">{text}</text>
</svg>
"""

out = Path(__file__).resolve().parent.parent / "docs" / "assets" / "apps"
out.mkdir(parents=True, exist_ok=True)
for name, (text, color) in APPS.items():
    size = 44 if len(text) == 1 else 34
    (out / f"{name}.svg").write_text(TEMPLATE.format(text=text, color=color, size=size), encoding="utf-8")
