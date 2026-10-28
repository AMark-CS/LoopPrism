#!/usr/bin/env bash
# Freeze the `lprism` CLI with PyInstaller into desktop/sidecar/dist/lprism/.
#
# Builds the dashboard (dashboard/dist), then runs PyInstaller with $PYTHON
# (default: python3), which must already have loopprism and
# pyinstaller installed:
#   pip install "$REPO_ROOT" pyinstaller
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

# The sidecar bundles a fresh build of the dashboard (see sidecar/lprism.spec).
(
  cd "$HERE/../dashboard"
  [ -d node_modules ] || npm ci
  npm run build
)

cd "$HERE/sidecar"
rm -rf dist build
"$PYTHON" -m PyInstaller --noconfirm --clean lprism.spec

# Smoke test the frozen binary.
./dist/lprism/lprism --version
