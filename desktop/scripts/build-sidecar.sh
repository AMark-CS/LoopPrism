#!/usr/bin/env bash
# Freeze the `lprism` CLI with PyInstaller into desktop/sidecar/dist/lprism/.
#
# Uses $PYTHON (default: python3) which must already have loopprism and
# pyinstaller installed:
#   pip install "$REPO_ROOT" pyinstaller
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

DIST_INDEX="$("$PYTHON" -c 'import loopprism, pathlib; print(pathlib.Path(loopprism.__file__).parent / "dashboard" / "dist" / "index.html")')"
if [ ! -f "$DIST_INDEX" ]; then
  echo "loopprism/dashboard/dist is missing from the installed package." >&2
  echo "Build the dashboard first: (cd dashboard && npm ci && npm run build)" >&2
  exit 1
fi

cd "$HERE/sidecar"
rm -rf dist build
"$PYTHON" -m PyInstaller --noconfirm --clean lprism.spec

# Smoke test the frozen binary.
./dist/lprism/lprism --version
