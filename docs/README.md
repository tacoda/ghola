<!-- voice-register: informational -->

# Documentation

Six pages. Read them in this order the first time.

| Page | Read it when |
|---|---|
| [ADOPTING.md](ADOPTING.md) | you have cloned this and want a pull request out of it today |
| [GUIDE.md](GUIDE.md) | you want the walkthrough, part by part |
| [LADDER.md](LADDER.md) | you are deciding where a rule belongs |
| [CUSTOMIZING.md](CUSTOMIZING.md) | you want to change something and want to know where it lives |
| [EVALS.md](EVALS.md) | you are about to edit a prompt |
| [LIMITATIONS.md](LIMITATIONS.md) | before any of it |

I put [LIMITATIONS.md](LIMITATIONS.md) last in that table and first in the
order. Every tool's documentation tells you what it does. That page tells you
what this one does badly, what it refuses to do on purpose, and what has already
gone wrong, so a reader can decide against it cheaply and early.

## Elsewhere

- [PLAN.md](../PLAN.md) is the phased plan: what is built, what each milestone
  had to prove, and what it taught.
- [examples/](../examples/) holds two working configurations at opposite ends of
  the range.
- [settings/README.md](../settings/README.md) is the reference for the
  configuration files themselves.
- [iii.dev/docs](https://iii.dev/docs) documents the framework underneath.

## The pictures

Every screenshot in these pages is real output, and none of it is drawn by hand.
The console frames in [img/console/](img/console) come from
`.tooling/shoot-console.mjs`, which holds one page open and shoots it each time a
job changes stage. The terminal frames in [img/terminal/](img/terminal) come from
`.tooling/shoot-terminal.mjs`, which runs the `make` target named in each title
bar and photographs its stdout.

```
cd .tooling && npm install                          # puppeteer, once
node shoot-terminal.mjs ../docs/img/terminal        # needs a running engine
node shoot-console.mjs <job-id> ../docs/img/console # run it beside a live job
```

Both scripts are tracked, because pictures go stale and the way to retake them
should not. Neither spends money: `shoot-terminal.mjs` lists read-only targets
only.
