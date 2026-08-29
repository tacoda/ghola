Carry out this change in the repository you have been given.

You have editing and shell functions. The working directory is an isolated
worktree on its own branch, so you are not touching anybody's checkout.

## The document so far

This is the job's own account of itself, and it
grows as the work moves. What was asked is in it, and so is the plan an
earlier turn made with this same repository in front of it.

$document

## How this is judged

The plan was made by an earlier turn with the same repository in front of it.
Follow it where it holds, and **say so where it does not**: a plan that turned
out to be wrong is useful information, and quietly diverging from it is not.

**Do not commit, and do not push.** Leave the work in the tree. A later stage
runs the delivery gate over the finished diff and then this repository's own
commit hook, and its refusal comes back to you verbatim as the brief for another
attempt. Committing yourself does not skip that gate — it is read either way —
but it does make the account of what happened harder to follow.

If you are genuinely blocked — contradictory requirements, a missing
credential, a choice that would destroy data or commit to a direction the spec
did not authorise — reply with a single line beginning `INTERRUPT:` and the
question. Only an opening line counts. Do not use it for preferences, for
naming, or for anything the codebase already answers: decide those, and say
that you decided.

## When you are done

This phase produces **an account of what you built**. Say what you changed and
why, including anywhere the plan turned out to be wrong.
