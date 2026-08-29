# Document the make targets in the README

## What

`README.md` describes the project layout and the stack, but it does not list
what `make` can actually do. The `Makefile` already carries a `##` description
on every target and a `help` target that prints them, so the information exists
and is simply not where a reader looks first.

Add a section to `README.md` listing the make targets and what each one does,
grouped so a newcomer can find the three they need on day one.

## Why

A reader who has just cloned this wants to know how to start it. Today they
have to open the Makefile or already know that `make help` exists.

## Acceptance criteria

- `README.md` gains a section documenting the make targets.
- The descriptions match the `##` comments in the `Makefile`. Do not invent a
  target that does not exist, and do not describe one as doing something the
  Makefile does not do.
- `make help` still works and is mentioned, because it stays the source of truth.
- Nothing outside `README.md` changes.

## Out of scope

Do not change the Makefile. Do not restructure the rest of the README.
