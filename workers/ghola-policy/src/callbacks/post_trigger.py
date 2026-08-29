"""What a call did, on the job's log.

Observes and never refuses, so it fails open: a crashed logger must not stop a
turn. Rewriting a result is possible at this seam and deliberately unused, because
a ladder that edits what the model sees after the fact is a ladder nobody can
audit from the transcript.

**M1 is the seam only.** The job log arrives with the factory in M4.
"""

import context


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        return context.CONTINUE
    return context.CONTINUE
