Run this software against the spec's acceptance criteria and report what you saw.

You can run commands. You **cannot** edit: the editing functions were never
granted to this phase, because a check that repairs what it finds is reporting
on a tree nobody else has.

## The spec

$spec

## What to produce

```
PROVEN: yes
- [x] <the criterion, as the spec words it>
      $ <the command you ran>
      <what it printed>
```

`PROVEN: yes`, `no`, or `partial` on the first line.

**Every criterion you claim needs a command under it.** A `PROVEN: yes` with no
command is downgraded to `unproven` automatically — evidence or it did not
happen. If you could not run something, say `partial` and name what you could
not check and why.
