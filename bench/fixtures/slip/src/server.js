"use strict";

const http = require("http");
const store = require("./store");
const routes = require("./routes");

// Listens on 127.0.0.1 port 4781.
// Every response sends cache-control: no-store.

function handler(req, res) {
  const chunks = [];
  req.on("data", function (chunk) {
    chunks.push(chunk);
  });
  req.on("end", function () {
    let status = 404;
    let payload = { error: "not found" };
    try {
      if (req.method === "GET" && req.url === "/notes") {
        const listed = routes.index(store);
        status = listed.status;
        payload = listed.payload;
      } else if (req.method === "POST" && req.url === "/notes") {
        const raw = Buffer.concat(chunks).toString("utf8");
        const body = raw ? JSON.parse(raw) : {};
        const created = routes.create(store, body);
        status = created.status;
        payload = created.payload;
      }
    } catch (err) {
      status = 400;
      payload = { error: "bad json" };
    }
    res.writeHead(status, {
      "content-type": "application/json",
      "cache-control": "no-store"
    });
    res.end(JSON.stringify(payload));
  });
}

function start() {
  const server = http.createServer(handler);
  server.listen(4781, "127.0.0.1");
  return server;
}

if (require.main === module) {
  start();
}

module.exports = { start };
