# -*- mode: python ; coding: utf-8 -*-
# Freezes the `lprism` CLI (entry.py) into a one-dir bundle:
#   sidecar/dist/lprism/lprism
# One-dir (not one-file) so launches don't unpack ~50 MB to /tmp every time.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
# uvicorn picks loops/protocols/lifespan implementations by string at runtime.
hiddenimports += collect_submodules("uvicorn")
# SQLAlchemy loads the async sqlite dialect lazily by URL scheme.
hiddenimports += collect_submodules("sqlalchemy.dialects.sqlite")
hiddenimports += ["aiosqlite"]
hiddenimports += collect_submodules("loopprism")
# Optional uvicorn[standard] accelerators; fine if absent.
for optional in ("uvloop", "httptools", "websockets", "watchfiles"):
    try:
        hiddenimports += collect_submodules(optional)
    except Exception:
        pass

# The React dashboard is served from loopprism/dashboard/dist (api/app.py finds
# it relative to its own __file__). Bundle a fresh build of dashboard/ rather
# than whatever copy is committed under src/, so the app never ships a stale UI.
import os

DASHBOARD_DIST = os.path.abspath(
    os.path.join(SPECPATH, "..", "..", "dashboard", "dist")
)
if not os.path.isfile(os.path.join(DASHBOARD_DIST, "index.html")):
    raise SystemExit(f"Build the dashboard first: {DASHBOARD_DIST} is missing")
datas = [
    d
    for d in collect_data_files("loopprism")
    if not d[1].replace(os.sep, "/").startswith("loopprism/dashboard/dist")
]
datas.append((DASHBOARD_DIST, "loopprism/dashboard/dist"))

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="lprism",
    console=True,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="lprism",
)
