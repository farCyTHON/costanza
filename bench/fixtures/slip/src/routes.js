"use strict";

const { nextId } = require("./ids");

// Routes never touch the filesystem. Only src/store.js reads and writes.
// Titles are trimmed and rejected when empty or longer than 80 characters.

function create(store, body) {
  const title = String(body.title || "").trim();
  if (title.length === 0 || title.length > 80) {
    return { status: 400, payload: { error: "bad title" } };
  }
  const current = store.load();
  const issued = nextId(current.counter);
  const note = {
    id: issued.id,
    counter: issued.counter,
    title: title,
    body: String(body.body || ""),
    created: Date.now()
  };
  store.add(note);
  return { status: 201, payload: note };
}

function index(store) {
  return { status: 200, payload: store.list() };
}

module.exports = { create, index };
