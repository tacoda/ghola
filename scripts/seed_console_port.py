"""Put the console's port back into config.yaml before the engine boots.

`http_port` is a startup seed, not a stored setting. The engine reads the
console's `config:` block on boot, applies it, then rewrites config.yaml with a
comment saying the value now lives in `config/console.yaml`. It does not: that
file holds UI preferences only, so the next boot falls back to the stock 3113
and collides with any other iii console on this machine.

So the seed is restored on every `make engine`. Nothing else in the stack needs
this. The http worker's port really did migrate into `config/http.yaml`, and the
worker manager's block in config.yaml is never touched.

Run it directly for the self-check:

    python3 scripts/seed_console_port.py --check
"""

import re
import sys
from pathlib import Path

PORT = 3133
CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"

# Matches the console entry and any comment the engine left in place of the
# block it stripped, so re-seeding replaces the comment rather than stacking
# a second `config:` under the same worker.
CONSOLE = re.compile(r"(?m)^(  - name: console\n)(    #.*\n)?")


def seed(text: str, port: int = PORT) -> str:
    """Return config.yaml text with the console's http_port seeded.

    Idempotent: text that already carries the seed is returned unchanged.
    """
    if f"http_port: {port}" in text:
        return text
    seeded, count = CONSOLE.subn(f"\\1    config:\n      http_port: {port}\n", text)
    if not count:
        raise ValueError("config.yaml has no `- name: console` worker to seed")
    return seeded


def _check() -> None:
    stripped = "workers:\n  - name: console\n    # value now lives in config/console.yaml\n  - name: http\n"
    once = seed(stripped)
    assert "http_port: 3133" in once, once
    assert "# value now lives" not in once, "the stripped comment should be replaced"
    assert seed(once) == once, "seeding twice must not stack a second config block"

    bare = "workers:\n  - name: console\n  - name: http\n"
    assert "http_port: 3133" in seed(bare)

    try:
        seed("workers:\n  - name: http\n")
    except ValueError:
        pass
    else:
        raise AssertionError("a config.yaml with no console entry must raise")

    print("seed_console_port: ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check()
        sys.exit(0)

    text = CONFIG.read_text()
    seeded = seed(text)
    if seeded == text:
        sys.exit(0)
    CONFIG.write_text(seeded)
    print(f"seeded console http_port {PORT}")
