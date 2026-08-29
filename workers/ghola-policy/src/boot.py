"""What this repository contributes to a turn: its ladder, and nothing else.

Not a harness. The harness is iii's, and the graph of workers, triggers and
functions is what runs a turn. What lives here is four callbacks at the seams
that harness offers.

**This worker registers no tools.** Reading, searching, listing, editing and
running are `coder::*` and `shell::*`, which the `shell` worker already ships;
the charter surfaces are `directory::*`. Rung 1 works the same over a function
id whoever registered it, so a tool written here would be a tool the framework
already has.

Callbacks are bound by convention rather than by a list: every module in
`callbacks/` binds to the hook point its filename names. A list here would be a
second list, and this design has twice been bitten by two lists disagreeing.

The worker holds no session state. A callback is told which job it is inside by
the per-send `metadata` the factory attaches, and answers back by triggering the
factory's own functions. So it can restart mid-job, run twice, or move to another
host without anything being lost.
"""

import importlib
import os
import sys
from pathlib import Path

from iii import InitOptions, register_worker

import context
import recorders

NAME = "ghola"

# The harness's own trigger types, as the installed worker spells them. The tech
# spec writes them with underscores and this build emits hyphens; an underscore
# binding registers without error and NEVER FIRES, so the names are pinned here
# and asserted by a test rather than typed from memory.
HOOK_POINTS = {
    "pre_generate": "harness::hook::pre-generate",
    "pre_trigger": "harness::hook::pre-trigger",
    "post_trigger": "harness::hook::post-trigger",
    "post_generate": "harness::hook::post-generate",
    "post_turn": "harness::hook::post-turn",
}

# ghola is not alone on these seams. On a stock engine `pre-generate` already
# carries `directory::pre-generate`, `memory::hook::pre-generate` and
# `fp::inject-guidance`, and `pre-trigger` already carries `approval::gate` and
# `shell::turns::on-pre-trigger`. Priority is therefore load-bearing rather than
# decorative: the charter has to arrive before the rules that reference it, and
# ghola's refusals run after `approval-gate` has had its say about holds.
#
# The two that only observe fail open. The two that can refuse stay fail-closed,
# which is the harness's default and the right one: a crashed gate must not wave
# writes through.
HOOK_CONFIG = {
    "pre_generate": {"priority": 50, "timeout_ms": 15000},
    "pre_trigger": {"priority": 50, "timeout_ms": 15000},
    "post_trigger": {"on_error": "fail_open"},
    "post_generate": {"on_error": "fail_open"},
}


def bind_hooks(worker) -> list[str]:
    """Every module in `callbacks/`, bound to the point its filename names."""
    # `callbacks/`, not `hooks/`: this repository already has hooks, the ones a
    # target repo ships in its own settings.json, and one directory cannot mean
    # both.
    folder = Path(__file__).resolve().parent / "callbacks"
    bound = []
    for module_path in sorted(folder.glob("*.py")):
        point = module_path.stem
        if point not in HOOK_POINTS:
            continue
        module = importlib.import_module(f"callbacks.{point}")
        function_id = f"{NAME}::hook::{point}"
        worker.register_function(function_id, module.handle)
        worker.register_trigger({
            "type": HOOK_POINTS[point],
            "function_id": function_id,
            "config": HOOK_CONFIG.get(point, {}),
        })
        bound.append(point)
    return bound


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    url = os.environ.get("III_URL", "ws://localhost:49154")
    worker = register_worker(url, InitOptions(worker_name="ghola-policy"))
    context.WORKER = worker

    bound = bind_hooks(worker)
    # The observability half: three workers decide things and announce them, and
    # none of them keeps a permanent record. This is where those announcements
    # land in one append-only log.
    recording = recorders.bind(worker)

    print(f"ghola-policy started on {url}")
    print(f"  hooks : {', '.join(bound) or 'none'}")
    print(f"  audit : {context.AUDIT.folder}")
    print(f"  recording: {', '.join(recording) or 'nothing'}")
    print("  tools : none. Reading, editing and running are coder::* and shell::*")
    print("  the turn loop is iii's harness worker; this carries the ladder")


if __name__ == "__main__":
    main()
