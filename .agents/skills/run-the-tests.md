---
id: run-the-tests
description: >
  Run `make test` and read the result. 675 tests, under a second, no engine and
  no API key.
why: >
  It is the cheapest check in the repository and the one most worth doing
  before anything else. A capability at rung 1 rather than prose because the
  command is in the Makefile and the Makefile travels with the clone.
---

# Run the tests

```bash
make test
```

No engine, no key, no money. It reads `tests/` and nothing else, so it works on
a fresh clone before `make setup` has finished thinking about your toolchain.

## Reading a failure

The test names are sentences and the docstrings carry the bug each one
prevents, so a failing name usually says what broke without opening the file.
Two classes of failure mean something specific:

- **`test_docs`** fails when a page names a `make` target that does not exist,
  links to a missing file, or a prompt names a field the factory does not
  supply. It is a documentation failure, not a code one.
- **A count in a docstring or in `README.md`** is not checked by anything. If
  you add tests, update `README.md`, which states the number twice.

## When it passes and you still are not done

`make test` sends no turn, so it proves nothing about a prompt. `make eval`
does, and it costs money. `docs/EVALS.md` says when to run it, and the short
answer is before any change to `prompts/`.
