"""What ghola adds in front of a call, now that the ladder is not its job.

**The ladder moved out.** Rules, layers, rungs, predicates and the refusal that
carries a rule's own words are the `ladder` worker, which binds this same
`harness::hook::pre-trigger` type itself and answers `continue`, `deny` or
`hold`. It was the one genuinely general thing in this repository, and a
general thing behind a factory's private interface is a thing nobody else can
use.

So three participants now sit on this hook, and they compose rather than
overlap:

| function | priority | what it decides |
|---|---|---|
| `approval::gate` | its own | whether a human has to answer first |
| `ladder::gate` | 60 | whether a rule refuses this call |
| `ghola::hook::pre_trigger` | 50 | what this *factory* knows that a rule cannot |

What is left here is the third row, and it is deliberately small: the things
that depend on a job existing. A rule cannot know that this turn has a live
sub-agent sharing its filesystem root, because that is a fact about the factory's
own bookkeeping rather than about the code being written.

**M1 is the seam only.** The single-writer refusal arrives with sub-agents, and
the job log arrives with the factory in M4.
"""

import context


def handle(payload: dict) -> dict:
    call = context.of(payload)
    if not call.known:
        # Not ghola's turn. Someone else's chat on the same engine, and the
        # ladder still applies to it because the ladder is not ours.
        return context.CONTINUE

    # M4 mounts the factory's own knowledge here:
    #
    #   if call.function_id == "harness::spawn":
    #       remember the child, because post-trigger never fires for a spawn
    #   if writing and this session has a live child:
    #       refuse — two writers in one worktree means one silently loses
    return context.CONTINUE
