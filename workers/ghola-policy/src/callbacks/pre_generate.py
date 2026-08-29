"""Rung 0: the repository's own instructions reach the model here.

The charter arrives through the seam rather than being pasted into the brief,
which is what lets it be scoped: the always-on pieces on the first generate, and
a scoped piece once the turn has gone near what it is about.

**M1 is the seam only.** The charter assembly arrives in M2. Note that ghola is
not alone on this hook: `directory::pre-generate` serves the repository's skills
and prompts, and `memory::hook::pre-generate` injects its banks' rules. What is
left for ghola is the path-scoped, layered half neither of those does.
"""

import context


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        return context.CONTINUE

    # M2 mounts the charter here:
    #   arriving = charter.for_paths(call.workspace, touched)
    #   return {"decision": "continue",
    #           "mutations": {"system_prompt": arriving}}
    return context.CONTINUE
