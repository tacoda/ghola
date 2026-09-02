---
id: ghola-registers-no-tools
description: >
  No worker in this repository registers a function a turn can call. Every tool
  a phase is granted belongs to a stock iii worker.
why: >
  It is the rule that keeps this repository small: if a worker does it, ghola
  does not. A tool registered here would be a second implementation of
  something the ecosystem already maintains, and the first thing to rot.
paths:
  - "workers/**"
---

# ghola registers no tools a turn can call

`coder::*` and `shell::*` are the `shell` worker. The charter surfaces are
`directory`. Worktrees, the forge, the approval hold, evaluation, the store,
the queues and the console are each somebody else's worker. What is left for
ghola is the stage graph and the briefs.

The two exceptions prove it. `ghola-ladder` registers seven functions and
`ghola-audit` registers six, and not one of them is in any phase's grant: they
serve the factory, the policy callbacks and the operator, never a model
mid-turn. So a phase's tools still all belong to a stock iii worker.

Adding a tool here means answering why the ecosystem should not have it
instead. `README.md` has the table of what ghola therefore does not write.
