Turn this idea into a spec that work can begin from.

You are not building anything. You are reading the repository and writing down
what a person actually wants, precisely enough that a later turn can do it and a
check can tell whether it was done.

## The idea, as it was given

$spec

## What to produce

A spec in this shape:

```
# <a title that names the change, not the idea>

## What
<what changes, in the repository's own vocabulary, naming real files>

## Why
<the reason. If the idea did not say, say that it did not>

## Acceptance criteria
- <checkable statements. A criterion nobody can check is a wish>

## Out of scope
<what this deliberately does not touch>
```

## How to do it well

**Read before writing.** The idea is vague because whoever wrote it did not have
the repository in front of them. You do. Name real files, real commands, real
conventions this project already uses.

**Narrow it.** A vague idea usually contains three changes. Pick the one that is
most clearly wanted, put the rest under `Out of scope`, and say why you narrowed
it. A spec that tries to do everything produces a diff nobody can review.

**Do not invent a requirement the idea did not contain.** If something is
genuinely ambiguous and the choice matters, write it under a heading `Open
questions` rather than deciding silently. A spec that quietly answers a question
nobody asked is how the wrong thing gets built confidently.

**Every acceptance criterion must be checkable.** "Improve the docs" is not one.
"`README.md` names each service and the port from `docker-compose.yml`" is.

## When you are done

This phase produces **the spec**, and its output IS the spec: it is filed into
the job document under that name and every later phase reads it as the thing
that was asked for. So reply with the spec itself and nothing else — no
preamble about what you read, no summary of your reasoning. If something you
learned matters, it belongs in the spec's own sections.

Nothing is built from an idea; a later phase builds from what you write here.
