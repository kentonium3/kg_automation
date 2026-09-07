---
title: Archive — moved to kg-auto-aux
doc_type: readme
audience: agents_and_humans
status: active
last_updated: '2026-09-07'
---

# Archive — moved

The frozen historical artifacts that lived here — legacy functional specs
(`func-spec/`, F001–F020), retired deploy scripts, superseded handoff records,
earlier architecture audits — **moved on 2026-09-07** to the private auxiliary
repo:

> **[`kentonium3/kg-auto-aux`](https://github.com/kentonium3/kg-auto-aux) → `archive/`**

131 files, copied byte-identical.

## Why

Not sensitivity — **portability**. `kg-automation` is public and the direction is
to genericize it so that someone else could adopt it. Frozen history of this
system is dead weight for such an adopter while remaining worth keeping for us.
Tracked in [#968](https://github.com/kentonium3/kg-automation/issues/968).

## Where the history is

**Here.** Only the working copy moved. This repo is public and its history is
permanent, so every prior revision of every archived file remains readable in
this repo's git history — `git log --all -- docs/archive/<path>` still resolves,
and any commit that predates 2026-09-07 still contains the files themselves.

`kg-auto-aux` holds the current copy; `kg-automation` holds the record of how it
got that way.

## This directory is not a place to add things

New archival material goes straight to `kg-auto-aux`. This file exists only so
that references to `docs/archive/` still land somewhere that explains itself.
