#!/bin/sh
# Recorder: put costanza on PATH, then run: sh demo/demo.sh
set -eu
if ! command -v costanza >/dev/null 2>&1; then
  echo "costanza is not on PATH" >&2
  exit 1
fi
demo=$(mktemp -d)
cd "$demo"
git init -q
run() {
  printf '\n$ %s\n' "$*"
  "$@"
}
run costanza init --name "sample" --agents none
run costanza decide "one handoff file at the repo root -- a new chat can read it"
run costanza status
run costanza list
run costanza handoff --with-inbox
printf '\nsample project left at %s\n' "$demo"
