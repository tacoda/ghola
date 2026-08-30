"""Read the audit log: is it intact, and what does it say.

    make audit            the summary, and whether the chain verifies
    make audit VERIFY=1   verification only, exit non-zero if it is broken

Both questions from one file. An auditor asks whether it can be trusted and an
engineer asks what it counts, and answering them from two stores is how the two
answers stop agreeing.

**The log belongs to `tacoda/audit-log`; this display belongs to ghola.** The
worker counts whatever field it is asked for and knows nothing about rungs, which
is correct: a rung is a ladder idea, and ghola is the thing composing the two.
So the general summary comes from there and the line about refusals is computed
here.

Reading the files directly rather than asking the worker, because a reader needs
no worker and asking the writer whether its own writing is intact is the wrong
shape.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITLOG = Path(os.environ.get("AUDITLOG") or ROOT.parent / "audit-log")
sys.path.insert(0, str(AUDITLOG / "src"))

try:
    import audit  # noqa: E402
    import audit_log  # noqa: E402
except ModuleNotFoundError:
    print(f"no audit-log at {AUDITLOG}")
    print("Clone tacoda/audit-log beside this repo, or set AUDITLOG to where it is.")
    raise SystemExit(2)

FOLDER = os.environ.get("AUDIT_LOG_DIR") or (ROOT / "audit")

# The same vocabulary the worker runs with, from the same variable. Reading the
# log with a different list than the one it was written under would make this
# command and `audit::verify` disagree about the same file, which is the failure
# a single source of the list exists to prevent.
KINDS = tuple(k.strip() for k in os.environ.get("AUDIT_LOG_KINDS", "").split(",")
              if k.strip())


def main() -> int:
    report = audit_log.summary(FOLDER, kinds=KINDS)

    if not report["files"]:
        print(f"no audit log at {FOLDER}")
        print("nothing has been recorded yet, which is different from nothing "
              "having happened. Run a turn.")
        return 0

    state = "INTACT" if report["verified"] else "BROKEN"
    print(f"{FOLDER}")
    print(f"  {report['entries']} entries in {len(report['files'])} file(s): {state}")
    if not report["verified"]:
        print(f"  verified through entry {report['verified_through']}; "
              "everything after it is unproven")
        for problem in report["problems"][:10]:
            print(f"    {problem}")

    if os.environ.get("VERIFY"):
        return 0 if report["verified"] else 1

    show("by kind", report["by"]["kind"])
    # ghola's own question, and the reason it is asked here: which rung is doing
    # the work. A backstop that starts catching everything is a signal about how
    # turns are writing, not an argument for tightening anything.
    entries, _ = audit_log.AuditLog(FOLDER).read()
    show("refusals by rung", audit.tally(entries, by="rung", kind="ladder.refused"),
         label="rung ")
    show("by actor", report["by"]["actor"], limit=12)
    return 0 if report["verified"] else 1


def show(heading: str, counts: dict, label: str = "", limit: int = 0) -> None:
    """One breakdown, or nothing at all when there is nothing to say."""
    if not counts:
        return
    print(f"\n  {heading}")
    for name, count in list(counts.items())[:limit or len(counts)]:
        print(f"    {count:6}  {label}{name}")


if __name__ == "__main__":
    raise SystemExit(main())
