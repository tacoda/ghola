# contracts

**Optional, like everything in `settings/`.** Each file here overrides a
built-in contract in `workers/ghola-core/src/contracts.py`; deleting one gets
you the built-in back.

A contract says what a phase's answer has to look like and what invalidates it.
The point is that **a check that grades itself is not a check**: `prove` claims
the software works and `review` claims the diff is sound, and both claims are
worth exactly what the evidence under them is worth.

Two rules do most of the work, and they are the same rule twice:

- `PROVEN: yes` with no command under any criterion becomes `unproven`.
  Evidence or it did not happen.
- `VERDICT: concerns` that names no file and line becomes `unreadable`. An
  objecting review that names nothing is a mood.

And one that matters more than either: **an answer that cannot be parsed is
never read as a pass.** It becomes `unreadable` or `unproven`, which a person
looks at. This is the failure where a check's output format drifts and reads as
approval for weeks.

```yaml
# verdict.yaml
marker: "VERDICT:"
values: [pass, concerns, blocker]
unparseable: unreadable
patterns:
  finding: '^\s*[-*]?\s*\S+\.\w+:\d+'
requires:
  - when: [concerns, blocker]
    at_least_one: finding
    otherwise: unreadable
    why: an objecting review that names nothing is a mood
```

A contract never fails a job. In a dark factory a check reports; only the merge
accepts. What a downgrade changes is what gets published, not whether the work
proceeds.

If your phase's output is too odd for this shape, write `parsers/<name>.py` with
a `parse(text) -> dict` and name it in the stage instead.
