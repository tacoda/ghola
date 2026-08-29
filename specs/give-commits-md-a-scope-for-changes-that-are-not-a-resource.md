# Give `commits.md` a scope for changes that are not a resource

## What

Improve `.claude/rules/commits.md` in the **charter** layer.

Amend the Scopes line to close the gap explicitly:

```
Scopes: `rooms`, `guests`, `reservations`, `stays`, `db`, `frontend`,
`backend`, `harness`, `deps`.

A change that fits none of them — the `Makefile`, `README.md`,
`docker-compose.yml`, `.gitignore`, `CLAUDE.md`, CI config — takes no scope.
Write `chore: <subject>` or `docs: <subject>` and do not stretch an existing
scope to reach it. `harness` means `.claude/**` and the commit gate, not
tooling in general.
```

Note that job 02855b21 landed a `README.md`-only change through this same gap and nobody recorded what scope it used. Two of the two jobs on record were out-of-scope commits.

## Why

`commits.md` declares empty `globs:`, so it governs every commit, and its scope list is `rooms`, `guests`, `reservations`, `stays`, `db`, `frontend`, `backend`, `harness`, `deps` — all resource or layer names. A change to `Makefile`, `README.md`, `docker-compose.yml`, `.gitignore` or `CLAUDE.md` fits none of them. `plan` found this, wrote "The next turn will hit this and burn a turn guessing", and pre-decided a fallback for it, spending a numbered section of a planning turn on a question the rule could have answered in one line. The `never-fired` signal names `commits` as a candidate for removal; this is the evidence that it should not be removed. It matters, it is carried at prose, and the gap in it is what cost something.

## Where this came from

Raised by ghola's improve lane from: job e4a633ad, `plan` output (document line 158), and the `never-fired` signal listing `commits`.

Nothing was applied. This spec goes through the same pipeline and the same pull
request as any other work, which is the rule that keeps the improve lane from
being the one thing escaping the factory's own gate.

## Acceptance criteria

- `.claude/rules/commits.md` reflects the change described above.
- The reason is written down where the next person will find it.
