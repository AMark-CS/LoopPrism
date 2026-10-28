#!/usr/bin/env node
// A fake GitHub release feed for testing the self-updater end to end.
//
//   node smoke-feed.js <installer.exe> <port> <installed-version>
//
// GET /releases  -> a release list offering 99.0.0 (the given installer) until it has been
//                   downloaded once, then the installed version, so the relaunched app sees
//                   no update and the test does not loop.
// GET /dl/<name> -> the installer
// GET /stats     -> { downloads }
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");

const [installer, port, installed] = process.argv.slice(2);
if (!installer || !port || !installed) {
  console.error("usage: smoke-feed.js <installer.exe> <port> <installed-version>");
  process.exit(2);
}
const bytes = fs.readFileSync(installer);
const sha = crypto.createHash("sha256").update(bytes).digest("hex");
let downloads = 0;

function release(version) {
  const name = `LoopPrism-${version}-x64.exe`;
  return {
    tag_name: `desktop-v${version}`,
    html_url: `http://127.0.0.1:${port}/release/${version}`,
    draft: false,
    prerelease: false,
    assets: [
      { name, browser_download_url: `http://127.0.0.1:${port}/dl/${name}`, size: bytes.length, digest: `sha256:${sha}` },
    ],
  };
}

http
  .createServer((req, res) => {
    if (req.url.startsWith("/releases")) {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify([release(downloads ? installed : "99.0.0")]));
    } else if (req.url.startsWith("/dl/")) {
      downloads += 1;
      res.setHeader("content-length", bytes.length);
      res.end(bytes);
    } else if (req.url.startsWith("/stats")) {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ downloads }));
    } else {
      res.statusCode = 404;
      res.end();
    }
  })
  .listen(Number(port), "127.0.0.1", () => console.log(`feed on ${port}, installer ${bytes.length} bytes`));
