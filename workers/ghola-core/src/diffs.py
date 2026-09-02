"""Splitting a unified diff into the files it touches.

The delivery gate at rung 4 handed the ladder one concatenated blob with no
path, cut at 200,000 characters. Three defects shared that one line, and they
share this fix.

A predicate answers `check(path, content, context)`, so a file is the unit it
was written for. Passing no path also skipped every path filter on the way in,
once in `Loaded.governing` and again in `gate.decide`, so a rule scoped to
`app/models/**` ran against every file in the change and its findings named
nothing. The cut then removed whatever fell past the limit, silently.

Text in, text out. That keeps the gate's hardest case a string in a test rather
than a repository with a large history behind it.
"""

from __future__ import annotations

import re

# `diff --git a/old b/new`. A path may contain spaces, so the b-side is taken as
# the rest of the line rather than by splitting on whitespace.
HEADER = re.compile(r"^diff --git a/(.*?) b/(.*)$")


def per_file(text: str) -> list[tuple[str, str]]:
    """Every file in a diff, with its patch, in the order they first appear.

    The b-side path is the one that travels. For a rename that is the new name,
    which is what a path-scoped rule is about, and for a deletion git repeats
    the old name there anyway.

    **A path appearing twice becomes one entry**, with both patches joined. The
    gate reads `against...HEAD` and `--cached`, and a file loose in both would
    otherwise be asked about twice, which would show a predicate reasoning over
    a whole file's change half of it at a time.

    Anything before the first header is dropped. git emits none, and a caller
    joining two diffs is the reason to say what happens to it.
    """
    patches: dict[str, list[str]] = {}
    order: list[str] = []
    path = ""

    for line in str(text or "").splitlines():
        found = HEADER.match(line)
        if found:
            path = found.group(2).strip() or found.group(1).strip()
            if path not in patches:
                patches[path] = []
                order.append(path)
        if not path:
            continue
        patches[path].append(line)

    return [(name, "\n".join(patches[name]).strip()) for name in order]
