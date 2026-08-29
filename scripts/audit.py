"""Read the audit log: is it intact, and what does it say.

    make audit            the summary, and whether the chain verifies
    make audit VERIFY=1   verification only, exit non-zero if it is broken

Both questions from one file. An auditor asks whether it can be trusted and an
engineer asks what it counts, and answering them from two stores is how the two
answers stop agreeing.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import audit_log  # noqa: E402

FOLDER = os.environ.get("GHOLA_AUDIT_DIR") or (ROOT / "audit")


def main() -> int:
    report = audit_log.summary(FOLDER)

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

    if report["by_kind"]:
        print("\n  by kind")
        for kind, count in report["by_kind"].items():
            print(f"    {count:6}  {kind}")
    if report["refusals_by_rung"]:
        print("\n  refusals by rung")
        for rung, count in report["refusals_by_rung"].items():
            print(f"    {count:6}  rung {rung}")
    if report["by_actor"]:
        print("\n  by actor")
        for actor, count in list(report["by_actor"].items())[:12]:
            print(f"    {count:6}  {actor}")
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
