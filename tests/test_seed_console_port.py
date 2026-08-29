"""The console port seed is the first thing in this repository that can be wrong
without saying so: the engine strips the block on every boot, and a console that
quietly returns to the stock 3113 loses to whatever is already there.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from seed_console_port import PORT, seed  # noqa: E402

STRIPPED = (
    "workers:\n"
    "  - name: console\n"
    "    # 'console': value now lives in the configuration worker at ./config/console.yaml.\n"
    "  - name: http\n"
)
BARE = "workers:\n  - name: console\n  - name: http\n"


class SeedConsolePort(unittest.TestCase):
    def test_seeds_a_bare_entry(self):
        self.assertIn(f"http_port: {PORT}", seed(BARE))

    def test_replaces_the_comment_the_engine_left(self):
        seeded = seed(STRIPPED)
        self.assertIn(f"http_port: {PORT}", seeded)
        self.assertNotIn("value now lives", seeded)

    def test_is_idempotent(self):
        once = seed(STRIPPED)
        self.assertEqual(once, seed(once))

    def test_leaves_other_workers_alone(self):
        self.assertIn("  - name: http\n", seed(STRIPPED))

    def test_raises_when_there_is_no_console_entry(self):
        with self.assertRaises(ValueError):
            seed("workers:\n  - name: http\n")


class TheEngineActuallyReadsIt(unittest.TestCase):
    """The seed is worthless if config.yaml has drifted out from under it."""

    def test_the_real_config_has_a_console_worker_to_seed(self):
        config = Path(__file__).resolve().parents[1] / "config.yaml"
        self.assertIn("- name: console", config.read_text())


if __name__ == "__main__":
    unittest.main()
