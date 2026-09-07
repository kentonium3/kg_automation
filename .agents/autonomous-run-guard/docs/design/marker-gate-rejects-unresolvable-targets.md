# Fix note — the marker gate must require the repository it asked to be swept

**Status**: design, revised after post-plan review, pre-build
**Vehicle**: kitty-light (rung 2) — design note → post-plan review ✅ → TDD → pre-merge review → PR
**Branch**: `fix/filing-guard-survives-org-rename` (lands before the branch reaches main)
**Source**: post-merge mission review of `filing-guard-survives-org-rename-01M0ZYJ5`

> ## Revision 2 — the first design was wrong and the point-cut caught it
>
> Revision 1 proposed rejecting *unresolvable* (dynamic) targets on the marker path. Two
> independent post-plan reviewers rejected it, and the measurement confirms them. Recorded here
> rather than quietly replaced, because what it got wrong is the useful part.
>
> **It would have re-armed the livelock this mission just repaired.** The runbook's §0 query 3
> passes its target as `${ref%#*}` — necessarily, because the 53 register refs span three
> repositories and no single literal is correct. Measured:
>
> ```
> query 3 verbatim -> ['register.read', 'sweep.register_refs']
>   gh segment target = '${ref%#*}'   names_upstream = True   in UPSTREAM_TARGETS = False
> ```
>
> Under revision 1, `sweep.register_refs` would never be earned: the operator lands on **3 of 4
> markers and is refused**. And the gate's **own printed remedy** for that marker *is* that loop —
> measured, it earns the marker today — so the gate would have printed an instruction that cannot
> satisfy the gate. That is this repo's named doctrine failure, reintroduced inside the mechanism
> built to prevent it.
>
> Revision 1's test plan was also internally contradictory: test 1 ("`--repo $X` awards nothing")
> and test 3 ("query 3 verbatim still earns") cannot both pass, because query 3 *is* a `--repo $X`
> query.
>
> **The deeper error**: a *deny* predicate was borrowed onto an *award* path. An award path needs an
> allowlist.

---

## The corrected diagnosis

A literal target is not a trustworthy one. Measured, all earning today, none of them a repository
the runbook asked to be swept:

```
gh issue list --repo octocat/hello-world        --author @me --state all -> ['sweep.authored']
gh issue list --repo kentonium3/scratch         --author @me --state all -> ['sweep.authored']
gh issue list --repo spec-kitty/spec-kitty-qa*  --author @me --state all -> ['sweep.authored']
gh issue list --repo spec-kitty/spec-kitty-qa   --author @me --state all -> []          <- honest
```

`octocat/hello-world` is the sharp case, and it is sharper than the "someone could create a scratch
repo" framing an earlier draft used: **creating anything is not required.** It is a public
repository that already exists, `gh` returns rc=0 against it, and the marker is awarded. That is
*cheaper* than the shell-variable bypass — one line of Bash, no setup — and no literal-ness test can
close it. The glob row is worse — bash expands
`spec-kitty/spec-kitty-qa*` to our own tracker when a matching path exists, so the sweep really does
hit our own tracker while the token reads as something else.

The question the marker path needs is not *"can I parse this?"* and not *"is this not-ours?"* — it
is a **positive** question, so that every unrecognised shape fails closed.

> ### Revision 3 — `UPSTREAM_TARGETS` membership is the wrong allowlist
>
> Both post-plan reviewers independently recommended membership in `UPSTREAM_TARGETS`. Building it
> would have turned an existing green test red, and that test encodes the mission's headline
> property.
>
> `test_a_post_rename_name_is_upstream_with_no_list_edit` (`tests/hooks/test_cp_before.py:1180`) is
> parametrised over `POST_RENAME_REPOS` — which includes `spec-kitty/spec-kitty` and
> `octocat/hello-world` — and asserts each **earns** its sweep marker *"with NO edit to any
> constant… that property IS the mission"* (FR-001, FR-002, SC-001). `UPSTREAM_TARGETS` holds the
> current EXPERIMENTAL names, so a post-rename name is a non-member. **A list-membership allowlist
> requires editing the list on rename — reintroducing, on the marker path, exactly the rename
> fragility this mission was built to eliminate.**
>
> Two runbooks also still legitimately sweep `Priivacy-ai/spec-kitty`, another non-member.

**The predicate that is actually right**: require the target to be a **well-formed repository
slug** — `^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$` — in addition to the existing `names_upstream`. This is
still enumerated-*allow*, but over the *syntax of a repository name* rather than over a maintained
list of names, so it converges by construction while staying rename-durable. Measured against every
shape found in review:

| target | accepted | why that is right |
|---|---|---|
| `spec-kitty/EXPERIMENTAL-spec-kitty` | yes | the sanctioned target |
| `spec-kitty/spec-kitty` | yes | **post-rename name — the mission's property, preserved** |
| `octocat/hello-world` | yes | unknown falls to the enforcing side (FR-002) |
| `Priivacy-ai/spec-kitty` | yes | legacy org, still swept by two runbooks |
| `$X`, `${ref%#*}` | no | C-1, closed |
| `…-qa*`, `…-q[a]`, `…-q?a` | no | glob bypass, closed |
| `{…,--json}`, `~/…` | no | brace and tilde, closed |
| `kentonium3/scratch` | yes | **residual, stated not hidden** — a literal irrelevant repo still earns; scoping evidence to the filing target is qa#291 item 4 |

No grammar predicate over another program's language, nothing to keep extending, and no list to keep
in step with reality.

---

## The change

### C-1 — `_hook_lib.detect_markers` (LIVE — reaches every clone via the committed gate)

| Marker | New condition | Why |
|---|---|---|
| `sweep.authored` | `names_upstream` **and** the target is a well-formed slug | closes `$X`, globs, braces, tildes; keeps post-rename names earning with no list edit |
| `sweep.recent_closed` | same | same |
| `sweep.register_refs` | **unchanged** — keeps `names_upstream`, takes no slug condition | see Revision 4 |
| `register.read` | unchanged | reads a local file; has no repository |

> ### Revision 4 — `sweep.register_refs` keeps `names_upstream` after all
>
> Revisions 2 and 3 both said to **drop** that call, on the argument that it was *"satisfiable
> solely via the defect being fixed, so it is pure liability."* **The build refuted it.** Deleting
> it turns **16 tests red** (15 before this change added its own) — it is what refuses a
> cross-check of *our own* tracker, in every flag form and every host-qualified spelling. The
> confident, well-argued reviewer was wrong here and the hedged one was right.
>
> The marker does also admit a dynamic target, which is the price of query 3 being expressible at
> all. That admission cannot be assembled into a bypass on its own, because the gate needs all four
> markers and the two above now demand a slug.
>
> Recorded as a revision rather than silently corrected, for the same reason the other two are:
> this file's whole subject is documents that assert things which are not true, and it does not get
> an exemption.

**What this closes, stated exactly.** The gate needs all four markers, and two of them can no
longer be earned by a target that is not a repository name — so the shell-variable, glob, brace and
tilde routes are dead.

**What it does NOT close, and a pre-merge review was right to press on it.** A *literal but
irrelevant* repository still earns. These four commands still satisfy the whole gate:

```
gh issue list --repo octocat/hello-world --author @me --state all
gh issue list --repo octocat/hello-world --state closed --search "closed:>=2026-08-01"
gh issue view 1 --repo octocat/hello-world --json state  # docs/spec-kitty-issues.md
cat docs/spec-kitty-issues.md
```

This is not an oversight in the fix; it is the boundary of what any target-shape predicate can do.
Refusing it needs the gate to know *which* repositories were required — either a maintained list
(rejected above: it breaks rename durability, and the existing suite asserts `octocat/hello-world`
classifies as upstream under FR-002) or markers that record what they were earned against, which is
qa#291 item 4.

Worth naming precisely, because it is the same fault one level up: **FR-002's "the unknown falls to
the enforcing side" is correct for FILING and wrong for AWARDING.** `test_a_post_rename_name_is_upstream_with_no_list_edit`
conflates two things in one parametrisation — "a post-rename spec-kitty name must still work",
which is the mission's property, and "any unknown repository earns a marker", which is the
polarity bug. Separating them is the shape of the eventual fix and is not attempted here.

So: **the C-1 hole is closed; the marker gate is not sound.** No claim in this change may say
otherwise.

Note the slug predicate leaves `UPSTREAM_TARGETS`' docstring intact — *"Used ONLY to build remedy
text (FR-013); it is never a classification input."* Revision 2 would have violated that line and
required revising it; revision 3 does not touch the constant at all. That the doctrine line and the
correct fix now agree is a small signal that the shape is right.

### H-1 — the filing guard's `queue` marker (one machine: the guard is unwired in committed config)

Two award branches, not one. Conditioning only the first moves the free marker down a line — onto
the branch the bug-reporting runbook actually tells people to use:

```
gh issue list --repo <ours> --search x --state all        -> ['queue']   # branch 1
python scripts/upstream_dedup.py --repo <ours> --query x  -> ['queue']   # branch 2
python3 -c 'pass  # upstream_dedup.py' --mechanism        -> ['intent','queue']   # executes nothing
```

Both branches are conditioned, but **not identically** — and the note originally said they would be,
which the build disproved.

- **`gh` branch**: full `names_upstream`. Its sanctioned form always names a repository.
- **dedup-script branch**: the weaker `not is_ours(target)`. Requiring `names_upstream` here turned
  three existing tests red, because the runbook's prescribed invocation is
  `upstream_dedup.py --query "<keywords>"` — **no `--repo` at all**; the script resolves the repository
  itself. This is the query-3 shape again: the sanctioned command's target is not in its argv, so a
  predicate demanding one refuses the prescribed path. A *named* target that is ours is refused; an
  unnamed one is credited, because nothing at this layer can tell what it resolves to. That
  remaining gap is qa#291 item 4.
- **both**: `-c` excluded. `python -c` runs inline code, never a script file, and
  `names_dedup_script` is a substring test over any token — so a payload that merely *mentions* the
  filename earned two markers while executing nothing. That is a **token command satisfying the
  gate**, which the gate's own `CLOSING_BLOCK` text explicitly forbids.

⚠ **Do not claim this restores SC-002.** It does not: sweeping one upstream repo still unlocks a
filing into a different upstream repo. Scoping evidence to the filing target requires storing the
swept repo *with* the marker and is qa#291 item 4 verbatim. Use ownership, note the gap, leave it.

Use ownership (`names_upstream`) here rather than allowlist membership: two runbooks still
legitimately sweep `Priivacy-ai/spec-kitty`, which is a non-member, and breaking them is not in
scope for this change.

### H-2 — the NFR-002 oracle

Revision 1 proposed asserting the observable verdict. **Measured: that is still blind.** A guard
mutated to spawn 14 real processes produced byte-identical stdout and exit codes on every command,
because twelve of the fifteen cases expect DENY and `run()` converts any injected error into a denial.
Verdict-asserting is strictly *weaker* than what is there now on those twelve.

What actually works — observe the execution boundary, not the verdict:

1. Patched entry points **record and then raise**; assert the record is empty, in addition to the
   verdict.
2. Install `sys.addaudithook` in the driver child process for `subprocess.Popen`, `os.system`,
   `os.exec`, `os.posix_spawn`, `os.spawn`, `os.fork` — the only oracle that sees a spawn regardless
   of import spelling or module attribute. It cannot be removed once installed, so it must never go
   in the pytest process.
3. Move patch installation **before** `import upstream_filing_guard`. Today the guard is imported
   first, so a mutation spelled `from subprocess import run` at module scope binds the real function
   and the patch never sees it — which makes the red-demonstration itself gameable.
4. Demonstrate red with `os.posix_spawn` inside `main`, because that defeats the *current* patch set
   and so proves the new oracle does work the old one could not.

The current patch set misses `os.posix_spawn`, `os.spawn*`, `os.execve`/`os.execl*`, `os.fork`,
`pty.spawn` and `subprocess.getstatusoutput`.

### M-3 — documentation

Two sites added by the mission's own diff name `UPSTREAM_PREFIXES`, deleted in the same commit:
`docs/runbooks/autonomous-run-protocol.md:367` and `docs/design/filing-guard-new-org-repoint.md:25`.

---

## Build order (never combine the first and last)

The risk being managed: `mission_lifecycle_gate.py` does `from hooks import _hook_lib as lib`
**outside any try**. A broken `_hook_lib` fails at import, before any handler exists. The PreToolUse
wrapper turns a non-zero exit into a deny, so **every Bash call in every clone is refused**; the
PostToolUse wrapper emits nothing silently; both discard stderr, and the deny text points at a file
that is present and fine. The traceback naming the real fault is thrown away.

**Escape hatch, which must be in the note because nobody deduces it at 3am**: the hook matcher is
`Bash` only. Read/Edit/Write still work — recover by editing `_hook_lib.py` back.

1. `_hook_lib` marker predicates + `UPSTREAM_TARGETS` docstring revision. Full `tests/hooks` run
   before anything else.
2. Guard's two `queue` branches (H-1).
3. Oracle rebuild (H-2).
4. Docs (M-3) last, so a doc-only revert is trivially separable.

`_marker_commands()` runs at **import time** (`MARKER_COMMANDS` is built at module level), so any
error in a new predicate that touches it fires during import — that is the deny-everything scenario,
not a test failure.

---

## Test plan (TDD — each must be shown red first)

⚠ **Every test must use a fresh session id.** The ledger is per-session and persistent under
`.git/spec-kitty-hooks/sessions/`; a session that has already banked markers will not show the
livelock, which is a false green on exactly the thing that matters most.

| # | Test | Red first? |
|---|---|---|
| 1 | `--repo $X` earns neither `sweep.authored` nor `sweep.recent_closed` | yes |
| 2 | glob (`…-qa*`), brace and tilde targets earn neither | yes |
| 3 | **post-rename names and `octocat/hello-world` still earn** — the mission's own property, which revision 2 would have broken | no — regression guard, and the reason revision 2 was rejected |
| 4 | **§0 queries 1 and 2 verbatim still earn their markers** | no — regression guard |
| 5 | **§0 query 3 verbatim still earns `sweep.register_refs`** | no — the revision-1 guard |
| 6 | **the gate's own `MARKER_COMMANDS` output, run through `detect_markers`, earns every marker it is printed for** | no — makes "a check that can never pass" a test failure rather than a doctrine hope |
| 7 | `gh issue view 291` with no `--repo` earns no `sweep.register_refs` | yes |
| 8 | guard: `gh issue list --repo <ours>` earns no `queue`; upstream still does | yes |
| 9 | guard: `upstream_dedup.py --repo <ours>` earns no `queue`; upstream still does | yes |
| 10 | guard: `python3 -c 'pass  # upstream_dedup.py'` earns nothing | yes |
| 11 | NFR-002 oracle red against `os.posix_spawn` in `main`, green against the real guard | yes |

Test 6 is the one worth keeping forever: it turns the failure mode that killed revision 1 into
something the suite catches automatically.

Pairs in both directions throughout, per NFR-005 — every "earns nothing" has a matching "still
earns", so the tests cannot pass by refusing everything.

## Deliberately not in this change

- **C-2, C-3** (the eight filing-guard bypass shapes, the false-premise abstain branch) — qa#292
  evidence, per decision. **No success claim here may imply the evidence gate is sound**: C-3 leaves
  a filing path needing no evidence at all — omit `--repo`, let `gh` resolve via the `upstream`
  remote, and the ledger is never read.
- **Evidence scoping** (marker records which repo it was earned against) — qa#291 item 4.
- **M-1, M-2** — corrections to `spec.md`, which is workflow-managed and belongs to a merged
  mission. Recorded in the mission review report instead.
