const net = require("node:net");

const HOST = "127.0.0.1";

function listen(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen({ port, host: HOST, exclusive: true }, () => {
      const { port: bound } = server.address();
      server.close(() => resolve(bound));
    });
  });
}

/**
 * Return `preferred` if it can be bound on loopback, otherwise an OS-assigned
 * free port. `avoid` lists ports that must not be returned (e.g. the other
 * service's port).
 */
async function pickPort(preferred, avoid = []) {
  if (!avoid.includes(preferred)) {
    try {
      return await listen(preferred);
    } catch {
      // taken; fall through
    }
  }
  for (let i = 0; i < 20; i++) {
    const port = await listen(0);
    if (!avoid.includes(port)) return port;
  }
  throw new Error("could not find a free port");
}

module.exports = { pickPort, HOST };
