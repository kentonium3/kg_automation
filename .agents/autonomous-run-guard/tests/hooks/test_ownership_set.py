"""The ownership set is tied to reality, offline (FR-007, NFR-001).

WHY THIS FILE EXISTS
--------------------
``OURS`` is the definition every classification in the guard hangs off, and it is a
hand-maintained list. "We would notice if it went stale" is a claim about attention,
not a mechanism. This file turns it into something that fails a build.

⚠ **THE ASYMMETRY IS INTENDED, AND IS THE WHOLE LIMIT OF THIS FILE.** This catches
*our own* repository being renamed, moved or re-owned — the day that happens, this
checkout's ``origin`` stops being a member of ``OURS`` and CI goes red. It catches
**nothing** about upstream renaming: whether ``UPSTREAM_TARGETS`` still names live
repositories is a *liveness* property, and no offline check can see it. That half
belongs to the §0 sweep, which runs against the real queues before every mission.
Nobody should later read this file as covering more than the first half.

OFFLINE BY CONSTRUCTION
-----------------------
``git remote get-url`` reads ``.git/config``. No network, no ``GH_TOKEN``, no ``gh``.
The charter's *"tests need no live credentials"* and NFR-001 both apply, and CI gates
PRs on this repository.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from hooks import _hook_lib as lib

REPO_ROOT = Path(__file__).resolve().parents[2]

#: ``owner/name`` out of either remote form git writes:
#:   https://github.com/owner/name.git   git@github.com:owner/name.git
#: Anchored at BOTH ends against the whole URL tail, so a host is never mistaken for an
#: owner — taking "the last two path segments" would make
#: ``https://evil.example/spec-kitty/spec-kitty-qa`` look like ours.
_REMOTE_RE = re.compile(
    r"^(?:https://|git@|ssh://git@)github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$"
)


def _origin_url() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"no origin remote in this checkout: {result.stderr.strip()}")
    return result.stdout.strip()


def owner_name(url: str) -> str | None:
    """``owner/name`` for a GitHub remote URL, or ``None`` when it is not one."""
    match = _REMOTE_RE.match(url)
    if match is None:
        return None
    return f"{match['owner']}/{match['name']}"


# =============================================================================
# The assertion this file exists for
# =============================================================================


def test_this_checkouts_origin_is_a_member_of_OURS() -> None:
    """The repository we are standing in must be one we say we own.

    Goes red the first CI run after our own repository is renamed or moved, and red
    if ``OURS`` is emptied, misspelled, or narrowed to exclude us. That is the entire
    mechanism keeping the ownership set from drifting the way the org prefixes it
    replaced did — silently, while still reporting success.
    """
    url = _origin_url()
    reference = owner_name(url)
    assert reference is not None, (
        f"origin {url!r} is not a GitHub remote this test can normalise — "
        "if the remote form changed, teach the normaliser, do not delete the check"
    )
    assert reference in lib.OURS, (
        f"this checkout's origin is {reference!r}, which is NOT in OURS ({sorted(lib.OURS)}). "
        "Either our own repository was renamed/moved and OURS was not updated, or OURS is "
        "wrong. Until this is fixed the guard classifies our own tracker as UPSTREAM."
    )


# =============================================================================
# The normaliser, pinned in both directions
# =============================================================================


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://github.com/spec-kitty/spec-kitty-qa.git", id="https-dot-git"),
        pytest.param("https://github.com/spec-kitty/spec-kitty-qa", id="https-bare"),
        pytest.param("https://github.com/spec-kitty/spec-kitty-qa/", id="https-trailing-slash"),
        pytest.param("git@github.com:spec-kitty/spec-kitty-qa.git", id="scp-dot-git"),
        pytest.param("git@github.com:spec-kitty/spec-kitty-qa", id="scp-bare"),
        pytest.param("ssh://git@github.com/spec-kitty/spec-kitty-qa.git", id="ssh-url"),
    ],
)
def test_every_remote_form_normalises_to_the_same_reference(url: str) -> None:
    """PAIRED POSITIVE. Without it, a normaliser returning ``None`` for everything
    would make the membership assertion above unreachable and this file vacuous."""
    assert owner_name(url) == "spec-kitty/spec-kitty-qa"


@pytest.mark.parametrize(
    "url,why",
    [
        pytest.param(
            "https://evil.example/spec-kitty/spec-kitty-qa",
            "a foreign host wearing our owner/name is not us",
            id="foreign-host",
        ),
        pytest.param(
            "https://github.com/spec-kitty-qa",
            "an owner with no repository is not a reference",
            id="no-repo",
        ),
        pytest.param("", "an empty remote is not a reference", id="empty"),
    ],
)
def test_a_url_that_is_not_our_forge_does_not_normalise(url: str, why: str) -> None:
    """The deny half. ``owner/name`` must be read from the forge we actually use —
    "last two path segments" would hand any host our identity."""
    assert owner_name(url) is None, why


# =============================================================================
# Shape of the set itself — the mistakes the criterion forbids
# =============================================================================


def test_ours_is_never_empty() -> None:
    """An empty set makes EVERYTHING upstream, including our own tracker. That is a
    silent, total inversion of the guard and it would pass every deny-only test."""
    assert lib.OURS, "OURS is empty — every repository, ours included, now classifies as upstream"


@pytest.mark.parametrize("reference", sorted(lib.OURS))
def test_every_entry_is_a_full_owner_name(reference: str) -> None:
    """A bare organisation is not a discriminator. After the rename ``spec-kitty/``
    matches upstream and us alike, so an entry that is an org — or an org with a
    trailing slash — would silently classify upstream repositories as ours."""
    assert not reference.endswith("/"), f"{reference!r} is an org prefix, not a repository"
    owner, _, name = reference.partition("/")
    assert owner and name and "/" not in name, f"{reference!r} is not a full owner/name"


@pytest.mark.parametrize("target", lib.UPSTREAM_TARGETS)
def test_every_upstream_target_is_a_full_owner_name(target: str) -> None:
    """Shape only, and the limit is worth stating plainly.

    ⚠ MEASURED BY MUTATION: shrinking `UPSTREAM_TARGETS` or renaming an entry to a
    repository that does not exist leaves this whole suite GREEN, and that is by design
    (`research.md` A-01). Whether a target is still live is a *liveness* property; no
    offline check can see it, and it belongs to the §0 sweep that runs against the real
    queues before every mission. Do not add an assertion here that appears to cover it —
    a check that cannot go red is the defect this mission exists to remove. What is
    offline-decidable is the SHAPE, and a malformed entry prints an unrunnable remedy.
    """
    assert not target.endswith("/"), f"{target!r} is an org prefix, not a repository"
    owner, _, name = target.partition("/")
    assert owner and name and "/" not in name, f"{target!r} is not a full owner/name"


def test_the_upstream_target_set_is_non_empty_and_has_no_duplicates() -> None:
    """An empty tuple prints remedies naming no repository at all — a denial with
    nothing runnable in it, which FR-009 forbids. A duplicate prints the same sweep
    twice, which reads as two queues and is how a copied entry hides."""
    assert lib.UPSTREAM_TARGETS, "no upstream target: every printed remedy names nothing"
    assert len(set(lib.UPSTREAM_TARGETS)) == len(lib.UPSTREAM_TARGETS), (
        f"duplicate entries in UPSTREAM_TARGETS: {lib.UPSTREAM_TARGETS}"
    )


def test_no_upstream_target_is_also_claimed_as_ours() -> None:
    """The two sets answer different questions and must never overlap: a repository we
    file defect reports into is, by the criterion, never one whose issues are our own
    work items."""
    ours = {reference.casefold() for reference in lib.OURS}
    overlap = ours & {target.casefold() for target in lib.UPSTREAM_TARGETS}
    assert not overlap, f"{sorted(overlap)} is listed as both ours and a repo we file into"
