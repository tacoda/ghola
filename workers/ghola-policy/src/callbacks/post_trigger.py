"""What a call did, on the audit log.

Observes and never refuses, so it fails open: a crashed recorder must not stop a
turn. Rewriting a result is possible at this seam and deliberately unused,
because a ladder that edits what the model sees after the fact is a ladder nobody
can audit from the transcript.

**This is the observability half of the governance pair.** A gate that decides is
worth nothing unless what it decided survives, and session transcripts do not
survive: they are prunable, scoped to a session, and record what was said rather
than what was decided. The audit log is append-only and hash-chained, so an
external auditor asking "who allowed this, on what evidence" has an answer that
does not depend on trusting the operator who is being audited.
"""

import context

# Calls worth a permanent record. Reading a file is not one: an audit log that
# records every read is an audit log nobody greps, and the signal drowns.
WORTH_RECORDING = ("worktree::", "github::", "gantry::", "approval::",
                   "coder::create-file", "coder::update-file", "coder::delete-file",
                   "coder::move", "shell::exec", "harness::spawn")


def worth_recording(function_id: str) -> bool:
    return any(function_id.startswith(prefix) for prefix in WORTH_RECORDING)


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known or not worth_recording(call.function_id):
        return context.CONTINUE

    data = payload.get("payload") or payload
    result = data.get("result") or {}
    context.record(
        "published" if call.function_id.startswith("github::") else "turn.completed",
        actor=call.function_id,
        subject=call.job_id or call.session_id,
        phase=call.phase,
        step=call.step,
        # The arguments are NOT recorded wholesale. They carry file contents and
        # occasionally credentials, and an audit log is the last place either
        # should be duplicated. What is recorded is what the call was about.
        about=str(data.get("call", {}).get("arguments", {}).get("path")
                  or data.get("call", {}).get("arguments", {}).get("command") or "")[:200],
        failed=bool(result.get("is_error")),
    )
    return context.CONTINUE
