---
id: no-ai-attribution
description: >
  No commit message, pull request, changelog or release note in this repository
  names Claude, an agent or any tool. No `Co-Authored-By` trailer for a model.
why: >
  The repository's operator is the author. Attribution added by a tool is a
  claim about who did the work, and it is wrong.
---

# No AI attribution

The author is the person who ran the job. Nothing ghola writes says otherwise.

This covers commit subjects and bodies, pull request titles and descriptions,
issue and ticket text, changelogs, and release notes. It does not cover code
comments, which describe the code rather than claiming credit for it.

`commit_message` in `workers/ghola-factory/src/actions.py` never adds a trailer,
so nothing has to remove one later.

## Where this is carried, and where it is not

Rung 2, by `.agents/hooks/no-ai-attribution.sh`, which refuses a `git commit`
whose message names a tool. Prose at rung 0 otherwise.

**It is not carried at rung 4**, and this file used to claim that it was. The
delivery gate does hand `ladder::evaluate` the text about to be published, but a
Python predicate is given only `path` and `content`: `publishing` reaches a
predicate written as a function id on the bus and nothing else. So no predicate
here can read a commit message, and `validate` said so the first time this file
declared `rung: delivery`.

Carrying it at 4 means writing that predicate as a bus function. Until somebody
does, the hook is the mechanism and rung 2 is the honest number.
