"""One line per container, from `compose::status` on stdin.

`make` is the whole operator surface, and thirty containers of pretty-printed
JSON is not a surface. The daemon's answer is the truth; this only makes it
scannable, and it prints `last_error` where there is one because a container
that failed is the only reason to read this at all.

Run it directly for the self-check:

    python3 scripts/status.py --check
"""

import json
import sys


def lines(status: dict) -> list[str]:
    """Return one line per container, then the ready count."""
    containers = status.get("containers", [])
    out = []
    for c in containers:
        line = f"  {c['container']:<22}{c['state']}"
        if c.get("last_error"):
            line += f"  {c['last_error']}"
        out.append(line)
    ready = sum(1 for c in containers if c["state"] == "ready")
    out.append(f"  {ready} of {len(containers)} ready")
    return out


def _check() -> None:
    got = lines(
        {
            "containers": [
                {"container": "harness", "state": "ready", "last_error": None},
                {"container": "ladder", "state": "failed", "last_error": "STARTUP_TIMEOUT"},
            ]
        }
    )
    assert got[0] == "  harness               ready", repr(got[0])
    assert got[1].endswith("failed  STARTUP_TIMEOUT"), repr(got[1])
    assert got[2] == "  1 of 2 ready", repr(got[2])
    assert lines({}) == ["  0 of 0 ready"], "no containers is not a crash"
    print("status: ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
        sys.exit(0)

    # A down daemon sends nothing, and a traceback is a worse answer than the
    # caller's own "compose is down" — so fail quietly and let it say that.
    try:
        status = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        sys.exit(1)

    print("\n".join(lines(status)))
