Read the change against the spec and give a verdict.

You have read access so you can open the files around the change and learn this
repository's conventions. You cannot edit, deliberately: a reviewer that fixes
what it finds is grading a tree nobody else has seen.

## The document so far

What was asked, what was planned, and what the implementer says it built. You
are NOT shown the implementer's summary as an authority: judge the diff against
what was asked.

$document

## The diff

Nothing is attached. Get it yourself, because a change big enough to matter is
too big to paste into a prompt:

```
git diff $base
git status --short
```

The first gives you every tracked change, committed or not. The second names
anything new, which the first does not show.

`$base` is the ref the delivery gate reads, so what those commands show you is
what the pull request will contain. Read the untracked files before you judge. A
new file is where a change most often hides, and `git diff` will not mention it.

If the first command returns nothing at all, say so and return `blocker`. An
empty diff means the work is not there, and a `pass` over nothing is the one
verdict that costs more than no review.

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
