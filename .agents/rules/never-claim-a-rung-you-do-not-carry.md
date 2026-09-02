---
id: never-claim-a-rung-you-do-not-carry
description: >
  A primitive reports the rung that actually enforces it. A rule listed at a
  mechanical rung with nothing running is reported as prose instead.
why: >
  A gate that fails open while the report says it passed is the one failure
  this whole model exists to prevent. A rule nobody enforces is survivable;
  a rule everybody believes is enforced is not.
---

# Never claim a rung you do not carry

The ladder's value is that the rung is true. Every shortcut it takes has to
degrade the claim rather than hide it.

Three places in this repository got this wrong and now do not:

- The delivery gate returned "not refused" when the ladder was unreachable, so
  a downed worker read as a clean change. It returns a problem now, and only an
  empty pair of answers reaches a commit.
- `prompts/review.md` promised a diff that nothing attached, so the reviewer
  read a heading with nothing under it. Every prompt is checked against the
  fields the factory supplies.
- A hook declared in a repository's `settings.json` lands at rung 2 only when
  its event can refuse something. An observing event lands at prose, because
  putting it at 2 would be the ladder claiming enforcement nothing performs.

When a shortcut is the right call, say what it cannot do. `docs/LIMITATIONS.md`
is where that goes, and a `ponytail:` comment is where the ceiling and the
upgrade path go in code.
