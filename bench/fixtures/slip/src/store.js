"use strict";

const fs = require("fs");
const path = require("path");

// List order is newest first by the created number.

const FILE = path.join("data", "notes.json");

function load() {
  if (!fs.existsSync(FILE)) {
    return { counter: 0, notes: [] };
  }
  return JSON.parse(fs.readFileSync(FILE, "utf8"));
}

function save(data) {
  fs.mkdirSync(path.dirname(FILE), { recursive: true });
  const tmp = FILE + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(data));
  fs.renameSync(tmp, FILE);
}

function list() {
  return load().notes.slice().sort(function (a, b) {
    return b.created - a.created;
  });
}

function add(note) {
  const data = load();
  data.notes.push(note);
  data.counter = note.counter;
  save(data);
}

module.exports = { add, list, load };
