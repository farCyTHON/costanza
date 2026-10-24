---
name: New importer
about: Propose lines from a saved transcript format
title: ""
---

**Source name.** The word you would pass to `costanza import` (`plain` and `aider` exist; `claude-code` exits 2 and does not parse JSONL).

**Published format.** Link the vendor's current document for the file. If no schema is published, say so. An unpublished format that changes between versions is not something this tool should guess.

**Sample.** A small file with secrets removed. Mark which lines should become proposals and which must be ignored (tool output, diffs, banners).

**Confidence.** Importers store `confidence: low` and never accept. Say if you expected anything else, and why.

**What you already tried.** `costanza import plain` on a text export is the supported path when the native file has no stable schema.
