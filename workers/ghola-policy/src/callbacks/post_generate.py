"""The verdict guard: a proof with no criteria is not a proof.

After the final assistant message, before the result is a result. This is where a
phase's output contract is enforced while the turn is still identifiable, which
matters for the audit log: a downgrade recorded here carries the session and the
phase, and one recorded later carries only a job id.

**It observes and never refuses.** The contract's job is to decide what the
answer is worth, not whether the work proceeds. In a dark factory a check
reports; only the merge accepts, and a `post_generate` that vetoed would turn a
weak review into a failed job.

The factory applies the same contract when it reads the completion. That is two
readers of one parser rather than two implementations: `contracts.read` is pure
and both call it, so they cannot disagree about what a turn said.
"""

import contracts as contractslib

import context

# Which phase is held to which contract. Read from the stage graph by the
# factory; here it is the mapping a turn can know without the job record, since
# the metadata carries the phase and nothing else.
BY_PHASE = {"prove": "proven", "review": "verdict"}


def assistant_text(data: dict) -> str:
    """The model's words, out of the shape this hook actually sends.

    `generated.message.content` is a LIST of typed blocks, not a string. The
    first version of this read `data["text"]`, found nothing, and returned
    quietly — so every contract downgrade went unrecorded and the guard looked
    like it was working. I stopped guessing key names and logged one real
    payload, which is what this shape is copied from.

    Thinking blocks are skipped: a model reasoning aloud about what verdict to
    give must not be read as giving one.
    """
    message = (data.get("generated") or {}).get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") in (None, "text"))
    return ""


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        return context.CONTINUE

    name = BY_PHASE.get(call.phase, "")
    if not name:
        return context.CONTINUE

    data = payload.get("payload") or payload
    text = assistant_text(data)
    if not text:
        return context.CONTINUE

    # A turn that stopped to ask has not produced an answer to grade, and
    # downgrading its question would be recording a verdict nobody gave.
    if contractslib.interrupt(text):
        context.record("turn.completed", actor=f"phase:{call.phase}",
                       subject=call.job_id or call.session_id, blocked=True)
        return context.CONTINUE

    answer = contractslib.read(text, contractslib.contract(name))
    if answer.downgraded:
        # The one thing worth recording from here. A check whose claim did not
        # survive its own contract is the signal that a phase's prompt has
        # drifted, and it is invisible anywhere else.
        context.record(
            "ladder.warned",
            actor=f"contract:{name}",
            subject=call.job_id or call.session_id,
            phase=call.phase,
            claimed=answer.downgraded_from,
            became=answer.value,
            why=answer.why,
        )

    return {
        "decision": "continue",
        "annotations": {
            f"ghola.{name}": answer.value,
            "ghola.downgraded": answer.downgraded,
        },
    }
