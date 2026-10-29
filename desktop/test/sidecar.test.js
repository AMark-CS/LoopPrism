"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const http = require("node:http");
const { Sidecar, REQUIRED_PROBE } = require("../src/sidecar");

function server(routes) {
  return new Promise((resolve) => {
    const s = http.createServer((req, res) => {
      const body = routes[req.url];
      res.statusCode = body === undefined ? 404 : 200;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify(body ?? {}));
    });
    s.listen(0, "127.0.0.1", () => resolve(s));
  });
}

async function detect(dashRoutes) {
  const proxy = await server({ "/health": { status: "ok", backends: [] } });
  const dash = await server({ "/api/health": { status: "ok" }, ...dashRoutes });
  const sc = new Sidecar({
    binary: "x", logFile: require("node:os").tmpdir() + "/lp-sidecar-test.log", pidFile: "x",
    preferred: { proxy: proxy.address().port, dashboard: dash.address().port },
  });
  try {
    return await sc.detectExternal();
  } finally {
    proxy.close();
    dash.close();
  }
}

test("a running LoopPrism with this version's API is reused", async () => {
  assert.ok(await detect({ [REQUIRED_PROBE]: { live_tools: true } }));
});

test("an older LoopPrism left running is not reused, so its old dashboard is never shown", async () => {
  assert.equal(await detect({}), null);
});
