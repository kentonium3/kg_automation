---
id: stop-hook-contract-measured
doc_type: reference
title: The Claude Code `Stop` hook contract, as measured
status: active
level: reference
owners: [kgale]
last_validated: 2026-08-26
version: 1.0.0
---

# The Claude Code `Stop` hook contract, as measured

**What this is.** Observed facts about the `Stop` hook event, captured live on **Claude Code 2.1.231**
(macOS, `permission_mode: auto`) on **2026-08-26**. Not derived from documentation.

**Why it exists separately from any mission.** These facts were measured during qa #278, which was
then abandoned in favour of a different approach. The facts outlive the approach: anyone who later
builds anything on the turn-end seam needs them, and re-acquiring them costs a live probe against a
running session. This page is the durable home so that probe is never repeated.

⚠ **Documentation is not evidence for this event family.** The hook reference shipped inside the
Claude Code binary documents `error_type` and `is_timeout` on `PostToolUseFailure`, and **neither
field exists** (see the register). Everything below was obtained by capture.

## The payload

Complete set of top-level keys observed:

| Key | Observed | Note |
|---|---|---|
| `hook_event_name` | `"Stop"` | |
| `session_id` | uuid | |
| `transcript_path` | absolute path to the session `.jsonl` | Present — but see `last_assistant_message`, which usually makes reading it unnecessary. |
| `cwd` | the directory the session is working in | |
| `stop_hook_active` | `false` normally, **`true`** on the consultation after a hook refused | The harness's own re-entry signal. |
| `last_assistant_message` | **the full text of the reply about to be sent** | 2196 bytes in the capture. |
| `permission_mode` | e.g. `"auto"` | |
| `effort` | e.g. `{"level": "high"}` | |
| `prompt_id` | uuid | Per prompt, not per session. |
| `background_tasks` | array | Empty in the capture. Exposes whether background work is pending. |
| `session_crons` | array | Empty in the capture. |

**Absent**: any timeout or duration field, and any field describing other hooks registered on the
same event.

## Refusing a turn end

Write this to **stdout** and exit **0**:

```json
{"decision": "block", "reason": "<text>"}
```

Measured behaviour when you do:

- **The turn does not end.** The agent is re-invoked and continues working.
- **`reason` reaches the agent verbatim**, prefixed `Stop hook feedback:`. It is the message the
  agent reads and acts on — not a log line. Whatever it says is the entirety of what the agent knows
  about why it was stopped and what to do instead, so it should name a concrete next action.
- **`stop_hook_active` is `true`** on the next consultation.

This is **not** the `hookSpecificOutput` envelope that `PreToolUse` uses. `decision` and `reason` are
top-level.

## Permitting a turn end

Exit **0** with **no stdout**. This is also what happens when the hook script crashes, is missing, or
is killed — silence permits.

## Three consequences worth writing down

**1. The harness already owns a re-entry guard.** `stop_hook_active` distinguishes "the agent is
yielding normally" from "the agent is yielding again after a hook held it open". Anything that needs
that distinction should read the flag rather than maintain its own counter or ledger. **Two
independent loop breakers can disagree, and the harness's wins.**

**2. You do not need to parse the transcript to see what the agent said.**
`last_assistant_message` carries the reply text. A design that rejects reading the agent's own words
on the grounds that it would require parsing a foreign format is rejecting it for a reason that does
not exist. (This exact error was made and shipped into a spec, a plan, a research decision, and an
adversarial review before one capture refuted it.)

**3. `background_tasks` is visible at turn end.** A turn that ends with background work pending is
materially different from one that ends with none — the pending task's completion notification
revives the session, while an empty list means the session is idle until a human types. Any reasoning
about whether an unattended run is "dead" can consult this directly.

## Related — doctrine derived from the same mission

This page is a **measured** record: every sentence above is a live-probe capture, which is why it can
say "do not re-measure". The reasoning that came out of the same abandoned mission — why `PreToolUse`
and `Stop` must fail in opposite directions, why `_hook_lib` is fail-CLOSED, and why recording must
gate refusing but never gate permitting — is not measurement and lives in
[`hook-fail-directions.md`](hook-fail-directions.md).

## Still unmeasured

Two things this capture did **not** establish. Do not assume either:

- **What the harness does with a `Stop` hook it killed on timeout.** A wrapper cannot emit a
  permitting response after being killed from outside, so a design that relies on "on timeout, permit"
  rests on unmeasured behaviour. If a timed-out `Stop` hook is treated as blocking or retried, that is
  a trap no wrapper can close.
- **How multiple hooks on one `Stop` event compose.** This repo already wires
  `spec-kitty session-stop` with no wrapper and no timeout. Whether a preceding hook can hang, block,
  or otherwise prevent a later one from running is unknown — and it bounds any safety claim of the
  form "every path permits".

## How the capture was done

Reproducible, and safe, in this order:

1. A dumper wired into `.claude/settings.local.json` (gitignored) that reads stdin, writes it
   verbatim, emits **nothing**, and exits **0** unconditionally — every exception swallowed.
2. Proven silent and exit-0 against valid, malformed, and empty stdin **before** being wired.
3. One real turn end produced the payload. **Hook registration took effect mid-session; no restart
   was needed.**
4. For the refusal shape, the dumper was extended to block **exactly once**: it writes a disarm
   marker **before** emitting the block, never after. Proven offline over four consecutive
   invocations — blocked once, silent three times — before being armed against a live session.

The ordering in step 4 is the safety property, not an implementation detail. Reversed, its failure
mode is "blocks forever", which traps the session.

⚠ **What not to do.** Do not establish what a side-effecting command *would* do by executing it.
A sibling harness asked whether a shell would word-split a string into a `gh issue create`
invocation and answered by running it under `bash -x` — which traces *and* executes — filing 27 real
issues on a vendor's public repository. Ending a turn is neither irreversible nor outward-facing,
which is why the probe above is safe and that one was not. The distinction is irreversibility, not
side effects in general.
