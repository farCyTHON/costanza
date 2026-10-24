<!-- costanza v1 | read fully before acting | one line per entry -->
# PROJECT: slip, local note inbox
stack: node, no dependencies
run: node src/server.js
layout: src/server.js (http), src/routes.js (handlers), src/store.js (files), src/ids.js (ids)
synced: local 2026-01-27

## NOW
doing: none
done: create a note, list notes
next: none
blocked: none

## DECISIONS
D1 note ids are n plus 8 lowercase hex digits from a counter -- UUIDs are too long here [files: src/ids.js]
D2 the server listens on 127.0.0.1 port 4781 -- the inbox stays on this machine [files: src/server.js]
D3 do not add authentication -- the loopback bind is the only guard

## REJECTED
X1 Express -- the http module is enough for two routes
X2 SQLite -- one JSON file is enough at this size

## RULES
R1 routes never touch the filesystem; only src/store.js reads and writes [files: src/routes.js, src/store.js]

## GOTCHAS
G1 a crash can leave data/notes.json.tmp behind -- delete that temp file on startup when the real file exists

## OPEN
