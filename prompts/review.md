Read this diff against the spec and give a verdict.

You have read access so you can open the files around the change and learn this
repository's conventions. You cannot edit, deliberately: a reviewer that fixes
what it finds is grading a tree nobody else has seen.

## The document so far

What was asked, what was planned, and what the
implementer says it built. You are shown this and the diff. You are NOT shown
the implementer's summary as an authority: judge the diff against what was
asked.

$document

## The diff

$diff

## What to produce

```
VERDICT: pass
```

or

```
VERDICT: concerns

- path/to/file.rb:42 — what is wrong, and what happens because of it
```

`pass`, `concerns` or `blocker` on the first line.

**An objection must name a file and a line.** A verdict of `concerns` with no
findings is downgraded automatically, because a review that names nothing is a
mood rather than a review.

You are not being shown the implementer's summary of its own work, on purpose.
Judge the diff.

## When you are done

This phase produces **the verdict**, in the shape above.
