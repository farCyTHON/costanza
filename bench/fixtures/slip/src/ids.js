"use strict";

// Note ids are n plus 8 lowercase hex digits from a counter, not UUIDs.

function nextId(counter) {
  const n = Number(counter) + 1;
  return { id: "n" + n.toString(16).padStart(8, "0"), counter: n };
}

module.exports = { nextId };
