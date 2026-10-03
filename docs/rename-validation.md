# LoopPrism rename — 2026-10-03

The project, repository, Python package, dashboard, and primary CLI are now
LoopPrism / `loopprism`. Legacy CLI, environment variables, and incoming
headers remain supported. Existing local databases/configuration are read
as a fallback without moving or deleting user data. See README for details.

Validation on Python 3.12:

- 51 tests passed; one existing `test_proxy_error_handling` failure returned
  an empty 502 response instead of the expected JSON. The identical failure
  was reproduced using the original pre-rename commit and same environment.
- New and legacy CLI `--version` entry points succeeded.
- Dashboard TypeScript/Vite production build succeeded and bundled title
  is LoopPrism. Old generated bundles were replaced; Git retains their history.
- Wheel build succeeded. No package was published to PyPI.

The dashboard lockfile referenced an inaccessible internal npm mirror.
Only its registry URLs were changed to the public npm registry; locked
versions and integrity hashes were retained. npm reported five existing
dependency vulnerabilities (one moderate, four high); no automatic dependency
upgrades were included in this rename.
