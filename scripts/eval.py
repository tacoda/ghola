"""Submit eval cases to the `eval` worker, and read what came back.

    make eval                      every case in evals/
    make eval CASE=prove-cites-evidence
    make eval RESULT=<evaluation_id>

ghola writes no runner. Each file in `evals/` is an `eval::start` request, and
this is the twenty lines that post them and print the answer.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = os.environ.get("GHOLA_MGR_PORT", "49154")


def trigger(function_id: str, payload: dict | None = None) -> dict:
    command = ["iii", "trigger", function_id, "--port", PORT]
    if payload is not None:
        command += ["--json", json.dumps(payload)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[:400])
    return json.loads(done.stdout or "{}")


def cases(only: str = "") -> list[Path]:
    found = sorted(p for p in (ROOT / "evals").glob("*.json"))
    return [p for p in found if not only or p.stem == only]


def show_result(evaluation_id: str) -> int:
    """What the evaluation found, as a person reads it.

    The per-run results live under `progress.runs`, each with its own
    `evaluation`. The first version of this read `report.control.runs`, found
    nothing, and printed "0/0 passed" for an evaluation that had discriminated
    perfectly — which is the worst shape a report can take, because it looks
    like a result.
    """
    answer = trigger("eval::result", {"evaluation_id": evaluation_id})
    report = answer.get("report") or {}
    runs = (answer.get("progress") or {}).get("runs") or []

    if not runs:
        print(f"{evaluation_id}: {answer.get('status', 'no runs yet')}")
        return 1

    by_role: dict[str, list] = {}
    for run in runs:
        by_role.setdefault(str(run.get("role") or "?"), []).append(run)

    for role in ("control", "treatment"):
        found = by_role.get(role) or []
        if not found:
            continue
        passed = sum(1 for r in found if r.get("passed"))
        label = str((report.get(role) or {}).get("label") or role)
        print(f"  {role:10} {label!r}: {passed}/{len(found)} passed")
        for reason in {str((r.get("evaluation") or {}).get("reason") or "")
                       for r in found}:
            if reason:
                print(f"      {reason[:110]}")

    delta = (report.get("delta") or {}).get("pass_rate")
    print(f"\n  pass rate delta : {delta}")
    print(f"  candidate eligible: {report.get('eligible')}")

    # Eligibility is the worker's own judgement and it is deliberately strict:
    # every treatment run must pass and its pass count must not regress. A
    # candidate that is merely no worse is not evidence that it is better.
    return 0


def main() -> int:
    if os.environ.get("RESULT"):
        return show_result(os.environ["RESULT"])

    only = os.environ.get("CASE", "").strip()
    chosen = cases(only)
    if not chosen:
        print(f"no eval case{f' called {only!r}' if only else 's'} in evals/")
        return 2

    for path in chosen:
        request = json.loads(path.read_text())
        try:
            answer = trigger("eval::start", request)
        except RuntimeError as exc:
            print(f"{path.stem}: could not start — {exc}")
            continue

        evaluation_id = str(answer.get("evaluation_id") or answer.get("id") or "")
        print(f"{path.stem}: started {evaluation_id or answer}")
        print(f"  make eval RESULT={evaluation_id}")

    print("\nEvaluations are durable and run in the background. `eval::list` shows")
    print("them; the console has a page at #/ext/eval-benchmarks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
