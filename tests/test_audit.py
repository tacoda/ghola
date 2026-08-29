"""The audit log: append-only, durable, and tamper-evident.

The third property is the one that matters and the one people skip. An
append-only file you can edit is not an audit log, so most of this file is about
detecting edits rather than about writing entries.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import audit  # noqa: E402
import audit_log  # noqa: E402


def chain(*kinds) -> list[dict]:
    entries, previous = [], None
    for index, kind in enumerate(kinds):
        previous = audit.next_entry(previous, kind, at=1000 + index, actor="test")
        entries.append(previous)
    return entries


class TheChain(unittest.TestCase):
    def test_a_clean_chain_verifies(self):
        result = audit.verify(chain("turn.started", "ladder.refused", "turn.completed"))
        self.assertTrue(result.ok, result.problems)
        self.assertEqual(result.verified_through, 2)

    def test_the_first_entry_follows_genesis(self):
        first = audit.next_entry(None, "turn.started", at=1)
        self.assertEqual(first["prev"], audit.GENESIS)
        self.assertEqual(first["seq"], 0)

    def test_an_empty_log_verifies_and_says_it_proved_nothing(self):
        result = audit.verify([])
        self.assertTrue(result.ok)
        self.assertEqual(result.verified_through, -1)


class DetectingTampering(unittest.TestCase):
    """Each of these is a thing an auditor is actually worried about."""

    def test_an_edited_entry_is_caught(self):
        entries = chain("turn.started", "published")
        entries[1]["detail"] = {"pull_request": "a different one"}
        result = audit.verify(entries)
        self.assertFalse(result.ok)
        self.assertIn("It was edited", result.problems[0])

    def test_a_deleted_entry_is_caught(self):
        entries = chain("turn.started", "ladder.refused", "published")
        del entries[1]
        result = audit.verify(entries)
        self.assertFalse(result.ok)

    def test_a_reordered_pair_is_caught(self):
        entries = chain("turn.started", "ladder.refused", "published")
        entries[1], entries[2] = entries[2], entries[1]
        self.assertFalse(audit.verify(entries).ok)

    def test_an_inserted_entry_is_caught(self):
        # The obvious attack: add a record saying it was approved.
        entries = chain("turn.started", "published")
        forged = audit.entry(1, entries[0]["hash"], "approval.resolved", at=1,
                             actor="nobody", detail={"decision": "allow"})
        entries.insert(1, forged)
        self.assertFalse(audit.verify(entries).ok)

    def test_the_report_names_where_it_stopped_trusting(self):
        # A verifier that answers only yes or no is useless in an audit, where
        # the question is what exactly is being claimed, and from when.
        entries = chain("turn.started", "ladder.refused", "published")
        entries[2]["actor"] = "someone else"
        result = audit.verify(entries)
        self.assertEqual(result.verified_through, 1)
        self.assertIn("entry 2", result.problems[0])

    def test_rehashing_an_edit_still_breaks_the_chain(self):
        # An attacker who knows the format edits the entry AND its hash. The
        # chain is what catches that: the next entry's `prev` no longer matches.
        entries = chain("turn.started", "published", "turn.completed")
        entries[1]["actor"] = "someone else"
        body = {k: v for k, v in entries[1].items() if k != "hash"}
        entries[1]["hash"] = audit.digest(body)
        result = audit.verify(entries)
        self.assertFalse(result.ok, "rehashing should not rescue an edit")


class Reading(unittest.TestCase):
    def test_a_truncated_last_line_is_skipped_rather_than_fatal(self):
        # Which is what a crash mid-append looks like. Refusing to read the log
        # because of it would lose every entry that did land.
        text = audit.as_line(chain("turn.started")[0]) + '{"seq": 1, "prev"'
        entries, problems = audit.parse(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(problems), 1)

    def test_blank_lines_are_ignored(self):
        text = "\n" + audit.as_line(chain("turn.started")[0]) + "\n\n"
        entries, problems = audit.parse(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(problems, [])

    def test_an_unknown_kind_is_noted_but_does_not_fail_verification(self):
        # A newer writer, not a tampered entry. Refusing to verify because the
        # log mentions an event this reader has not heard of would make the
        # format unupgradeable.
        entries = [audit.next_entry(None, "something.new", at=1)]
        result = audit.verify(entries)
        self.assertTrue(result.ok)
        self.assertTrue(result.problems)


class OnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = audit_log.AuditLog(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_entries_append_and_verify(self):
        self.log.append("turn.started", actor="ghola", subject="job-1")
        self.log.append("published", actor="ghola", subject="job-1")
        self.assertTrue(self.log.verify().ok)
        self.assertEqual(len(self.log.read()[0]), 2)

    def test_a_new_process_continues_the_chain(self):
        # A restarted writer that started a fresh chain would produce a log
        # whose verification fails at exactly the restart.
        self.log.append("turn.started")
        reopened = audit_log.AuditLog(self.tmp.name)
        reopened.append("turn.completed")
        self.assertTrue(audit_log.AuditLog(self.tmp.name).verify().ok)

    def test_rotation_seals_a_file_and_keeps_the_chain(self):
        small = audit_log.AuditLog(self.tmp.name, rotate_bytes=200)
        for _ in range(8):
            small.append("turn.started", actor="a" * 20)
        self.assertGreater(len(small.files()), 1, "should have rotated")
        self.assertTrue(small.verify().ok, "the chain must span the files")

    def test_editing_a_sealed_file_is_caught(self):
        self.log.append("turn.started")
        self.log.append("published", detail={"pr": 1})
        path = self.log.files()[0]
        path.write_text(path.read_text().replace('"pr":1', '"pr":2'))
        self.assertFalse(audit_log.AuditLog(self.tmp.name).verify().ok)

    def test_the_summary_answers_both_questions(self):
        self.log.append("ladder.refused", actor="no-secrets", detail={"rung": 3})
        self.log.append("ladder.refused", actor="no-secrets", detail={"rung": 4})
        self.log.append("published", actor="ghola")
        report = audit_log.summary(self.tmp.name)
        self.assertTrue(report["verified"])
        self.assertEqual(report["by_kind"]["ladder.refused"], 2)
        self.assertEqual(report["refusals_by_rung"], {"3": 1, "4": 1})


class Statistics(unittest.TestCase):
    def test_refusals_are_counted_per_rung(self):
        # A rung carried as a backstop that starts doing all the work is a
        # signal about how turns are writing. Neither reading is available
        # without this count.
        entries = [
            audit.entry(0, audit.GENESIS, "ladder.refused", 1, detail={"rung": 3}),
        ]
        entries.append(audit.entry(1, entries[0]["hash"], "ladder.refused", 2,
                                   detail={"rung": 4}))
        entries.append(audit.entry(2, entries[1]["hash"], "ladder.refused", 3,
                                   detail={"rung": 4}))
        self.assertEqual(audit.refusals_by_rung(entries), {"3": 1, "4": 2})

    def test_tally_sorts_by_count(self):
        entries = chain("turn.started", "turn.started", "published")
        self.assertEqual(list(audit.tally(entries))[0], "turn.started")


if __name__ == "__main__":
    unittest.main()


class TwoWritersAtOnce(unittest.TestCase):
    """Multi-writer is the NORMAL case here, not an edge case.

    The policy worker records what the ladder and the approval gate decided; the
    factory records stage transitions. They are separate processes appending to
    one log. The first version held only a thread lock and an in-memory tail, so
    their `prev` hashes interleaved and the first real run produced a log that
    failed its own verification — which is indistinguishable from tampering.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_store_objects_interleaving_keep_one_valid_chain(self):
        # Two AuditLog objects stand in for two workers: separate tails, one
        # directory.
        a = audit_log.AuditLog(self.tmp.name)
        b = audit_log.AuditLog(self.tmp.name)
        for i in range(12):
            (a if i % 2 == 0 else b).append("turn.completed", actor=f"w{i % 2}")

        check = audit_log.AuditLog(self.tmp.name).verify()
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.entries, 12)

    def test_concurrent_threads_keep_one_valid_chain(self):
        import threading
        logs = [audit_log.AuditLog(self.tmp.name) for _ in range(4)]

        def write(log, n):
            for _ in range(8):
                log.append("stage.left", actor=f"t{n}")

        threads = [threading.Thread(target=write, args=(log, n))
                   for n, log in enumerate(logs)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        check = audit_log.AuditLog(self.tmp.name).verify()
        self.assertTrue(check.ok, check.problems)
        self.assertEqual(check.entries, 32)

    def test_the_lock_file_is_not_read_as_a_log(self):
        log = audit_log.AuditLog(self.tmp.name)
        log.append("turn.completed")
        self.assertEqual(len(log.files()), 1)
