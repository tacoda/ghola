"""The verdict guard: a proof with no criteria is not a proof.

After the final assistant message, before the result is a result. This is where a
phase's output contract is enforced: an objecting review with no findings, or a
`PROVEN: yes` with no command under any criterion, is downgraded rather than
believed.

Observe-only at this seam, so the downgrade is recorded on the job rather than
refused here.

**M1 is the seam only.** The contracts arrive in M6.
"""

import context


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        return context.CONTINUE
    return context.CONTINUE
