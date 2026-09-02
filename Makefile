# ghola. `make` is the whole operator surface: there is no CLI to learn.
#
# Three steps, and `make setup` is step one:
#
#   1. clone the repo          git clone … && make setup
#   2. add config and scripts  name a repo in repos.local.toml, edit settings/
#   3. tell it to do work      make submit SPEC=specs/x.md REPO=../repo

.PHONY: help setup doctor install submit up down logs status stop restart \
        call schema models console config pipeline jobs turn idea work test test-live eval audit \
        improve proposals accept repos clean

VENV := .venv
PY   := $(VENV)/bin/python
LOGS := .logs

CONSOLE_PORT := 3133
STREAM_PORT  := 3132
MGR_PORT     := 49154
GOVERNED_PORT := 49155

# Sourced for what `make` itself runs — `turn`, `test-live`, and the compose
# daemon's own environment, which is where the `${LADDER}`-style expansions in
# worker-compose.yaml are read from. The workers no longer inherit it: each one
# that needs a credential names `env_file: [./.env]` on its own container, which
# is why a provider started without a key is now a readable failure rather than
# a router with no models and every turn dying at `router::provider::resolve`.
ENV := set -a; [ -f .env ] && . ./.env; set +a;
RUN := $(ENV) PYTHONUNBUFFERED=1 GHOLA_ROOT=$(PWD) III_URL=ws://localhost:$(MGR_PORT)

help:
	@echo "getting started"
	@echo "  make setup      everything a fresh clone needs, then says what is next"
	@echo "  make doctor     what is missing, before you waste a turn finding out"
	@echo ""
	@echo "running it"
	@echo "  make up         the whole project, in the background. Blocks until ready"
	@echo "  make down       all of it, engine included"
	@echo "  make restart    every worker, same engine"
	@echo "  make status     what is up, per container"
	@echo "  make logs       follow what every worker is printing"
	@echo ""
	@echo "doing work                                    $$ = sends a paid turn"
	@echo '  make turn PHASE=plan PROMPT="..." [WORKSPACE=../repo]        $$'
	@echo "  make config     the effective settings, and where each value came from"
	@echo "  make pipeline   the stage graph as it will run, and what is wrong with it"
	@echo '  make submit SPEC=specs/x.md REPO=../repo SLUG=owner/name     $$'
	@echo '  make idea IDEA="a rough sentence" REPO=../repo               $$'
	@echo "                  # an idea is refined into a spec before anything is built"
	@echo "  make jobs       every job, newest first"
	@echo "  make repos      every target repository, and what is wrong with it"
	@echo "  make audit      the append-only record: intact? and what it says"
	@echo "  make models     what the router can actually reach"
	@echo ""
	@echo "improving it"
	@echo "  make improve [REPO=../repo]   read what went wrong, propose what helps  $$"
	@echo "  make proposals [RUN=abc123]   what it staged. Nothing is applied"
	@echo "  make accept RUN=abc123 N=0    a spec in specs/, or a move on the ladder"
	@echo ""
	@echo "checking it"
	@echo "  make test       pure and worker tests. Seconds, no engine, no money"
	@echo "  make test-live  framework contract tests. Needs a running engine"
	@echo "  make eval       A/B evals through the eval worker                     $$"
	@echo ""
	@echo "asking the engine"
	@echo "  make call FN=harness::status [JSON='{...}']"
	@echo "  make schema FN=harness::send"

# ---------------------------------------------------------------- step one

# Everything a fresh clone needs, in the order it needs it. Idempotent: running
# it again after adding a dependency is the supported way to install one.
setup: doctor install
	@[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "  wrote .env from the example"; }
	@# The one file a clone cannot ship filled in: it names directories on this
	@# machine. Same split as .env, and the tracked repos.toml is its examples.
	@[ -f repos.local.toml ] || { \
		echo "# This machine's repositories. Not tracked; wins over repos.toml." > repos.local.toml; \
		echo "# Copy an example out of repos.toml and edit the path." >> repos.local.toml; \
		echo "  wrote an empty repos.local.toml"; }
	@echo ""
	@echo "ready. Next:"
	@echo "  1. put your ANTHROPIC_API_KEY in .env"
	@# Single quotes: a backtick inside a double-quoted echo is a shell command
	@# substitution, and make would run `forge = "local"` as a command.
	@echo '  2. name a repository in repos.local.toml — repos.toml has two examples,'
	@echo '     and the forge = "local" one needs no account and no token'
	@echo "  3. make up"
	@echo "  4. make submit SPEC=specs/x.md REPO=/path/to/that/repo"

# Named separately because the answer to "why did that fail" is usually here,
# and finding out before a paid turn is the whole point.
doctor:
	@echo "checking what ghola needs:"
	@for tool in iii uv git gh python3; do \
		if command -v $$tool >/dev/null 2>&1; then \
			printf '  %-9s %s\n' "$$tool" "$$($$tool --version 2>&1 | head -1 | cut -c1-46)"; \
		else \
			printf '  %-9s MISSING\n' "$$tool"; \
		fi; \
	done
	@# The pins live in worker-compose.yaml now. iii 0.23 deleted `iii worker
	@# add` and iii.lock with it: `version:` under a container IS the lock.
	@printf '  %-9s ' "harness"; \
		grep -A2 '^  harness:$$' worker-compose.yaml 2>/dev/null \
			| sed -n 's/.*version: "\(.*\)"/\1/p' | grep . \
		|| echo "not pinned in worker-compose.yaml"
	@printf '  %-9s ' ".env"; \
		{ [ -f .env ] && grep -q '^ANTHROPIC_API_KEY=.\+' .env && echo "ANTHROPIC_API_KEY set"; } \
		|| echo "no ANTHROPIC_API_KEY yet"
	@# Which provider serves the two swappable workers. Both ship bundled, so
	@# this line is boring until somebody swaps one, and on the day they do it is
	@# the first place to look when `ladder::list` answers differently.
	@printf '  %-9s %s' "ladder" "$(call provider,$(LADDER))"; \
		test -d $(LADDER) && echo "" || echo "  MISSING at $(LADDER)"
	@printf '  %-9s %s' "record" "$(call provider,$(AUDITLOG))"; \
		test -d $(AUDITLOG) && echo "" || echo "  MISSING at $(AUDITLOG): nothing would be recorded"
	@# The WORKER's identity, not this shell's. They are routinely different:
	@# the shell has a keyring login and the engine has whatever GH_TOKEN was in
	@# its environment, and only the worker's one opens pull requests.
	@printf '  %-9s ' "gh (worker)"; \
		iii trigger github::exec --json '{"args":["api","user","--jq",".login"]}' \
			--port $(MGR_PORT) 2>/dev/null \
			| python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("stdout") or "").strip() or "unknown")' \
		2>/dev/null || echo "engine not running"
	@# The identity that PUSHES and the identity that opens a PULL REQUEST are
	@# not the same thing. git may use an ssh host alias while gh uses a token
	@# from the environment, and the mismatch fails only at `pr create`, after a
	@# job has paid for a worktree, a plan, a run and two checks.
	@echo ""
	@echo "target repositories (repos.toml + repos.local.toml):"
	@$(PY) scripts/repos.py 2>/dev/null || python3 scripts/repos.py
	@# Only the ones whose forge needs an account. A `local` repository opens no
	@# pull request and needs no token, which is the shortest path to a first run.
	@for slug in $$($(PY) scripts/repos.py --slugs 2>/dev/null || python3 scripts/repos.py --slugs); do \
		printf '  %-9s ' "$$slug"; \
		if iii trigger github::exec --json "{\"args\":[\"api\",\"repos/$$slug\",\"--jq\",\".permissions.push\"]}" \
			--port $(MGR_PORT) 2>/dev/null | grep -q true; then \
			echo "the worker can open pull requests here"; \
		else \
			echo "NO PR ACCESS. git may still push over ssh; the API is what opens the PR"; \
		fi; \
	done

# `--allow-existing` because this runs again every time a package gains a
# dependency, and refusing to touch an existing venv made the obvious command
# fail with an error about the venv rather than doing the install.
install:
	@uv venv $(VENV) --allow-existing
	@uv pip install --quiet --python $(PY) -e workers/ghola-core -e workers/ghola-policy -e workers/ghola-factory
	@echo "  installed ghola-core, ghola-policy and ghola-factory into $(VENV)"

# ---------------------------------------------------------------- running

# The whole process surface is `worker-compose.yaml` now: the engine, the thirty
# stock workers and ghola's own four, with their versions pinned in the same
# file. `iii compose` starts and supervises the lot, so the five targets that
# used to hand-roll one process each are gone, and so are the `pgrep` patterns
# that had to tell them apart.
#
# The ladder and the record are still BUNDLED by default and swappable by
# variable — the compose file reads both of these:
#
#     make up LADDER=../ladder LADDER_PY=../ladder/.venv/bin/python
#
# The interpreter is now a variable rather than a wildcard probe, because an
# external checkout has its own dependencies and ghola's venv was built for
# ghola's pins.
LADDER ?= ./workers/ghola-ladder
AUDITLOG ?= ./workers/ghola-audit
LADDER_PY ?= $(PY)
AUDITLOG_PY ?= $(PY)

# Exported, because the compose file reads these four out of the ENVIRONMENT.
# A make variable that is not exported reaches the recipe and stops there, so
# `make up LADDER=../ladder` would have silently started the bundled ladder.
export LADDER AUDITLOG LADDER_PY AUDITLOG_PY

# Which provider is serving, for `make status` and `make doctor`. A reader who
# swapped one in three weeks ago should not have to remember that they did.
provider = $(if $(filter ./workers/%,$(1)),(bundled),(external: $(1)))

# Step three: a spec and a repo.
submit:
	@test -n "$(SPEC)" || { echo 'usage: make submit SPEC=specs/x.md REPO=../repo [SLUG=owner/name]'; exit 2; }
	@$(MAKE) --no-print-directory call FN=ghola::submit \
		JSON='{"spec":"$(SPEC)","repo":"$(REPO)","repo_slug":"$(SLUG)"}'

# An IDEA rather than a spec: rough, and refined into one before anything is
# built. A spec somebody wrote carefully is not rewritten; an idea somebody
# typed in a hurry has to become one first.
idea:
	@test -n "$(IDEA)" || { echo 'usage: make idea IDEA="a sentence" REPO=../repo'; exit 2; }
	@$(MAKE) --no-print-directory call FN=ghola::submit \
		JSON='{"idea":"$(IDEA)","repo":"$(REPO)","repo_slug":"$(SLUG)"}'

# The stage graph as it will actually run, and anything wrong with it. Read this
# before submitting rather than discovering a broken stage two turns in.
pipeline:
	@$(MAKE) --no-print-directory call FN=ghola::pipeline

jobs:
	@$(MAKE) --no-print-directory call FN=ghola::jobs

# Every target repository, from repos.toml and repos.local.toml together, with
# whatever is wrong with each. Needs no engine.
repos:
	@$(PY) scripts/repos.py

# Backgrounded, because remembering a foreground terminal is a thing to
# remember rather than a design. `make logs` is how you watch it.
#
# The second call is the readiness check. `compose::up` is idempotent — ready
# containers stay as they are — and it BLOCKS until every container has
# registered or one has failed. That is what two ninety-second sleep loops and a
# `sleep 4` used to approximate, and they were approximating it wrong: the loops
# proved the router was up and then started five processes hoping.
up:
	@mkdir -p $(LOGS)
	@pgrep -f '[i]ii compose --up' >/dev/null || { \
		($(ENV) iii compose --up > $(LOGS)/compose.log 2>&1 &); \
		printf 'starting '; }
	@# `compose::up` is the readiness gate, and waiting for the FUNCTION is the
	@# wait. The daemon registers its read-only calls as soon as it connects and
	@# withholds the mutating ones until the operation in flight finishes, so
	@# `compose::up` existing is exactly "the project is up or it gave up".
	@# Polling `compose::list` instead answered on the first second and then the
	@# call landed in the gap with `function_not_found`.
	@for i in $$(seq 1 600); do \
		iii trigger compose::up --port $(MGR_PORT) --timeout-ms 600000 >/dev/null 2>&1 && break; \
		pgrep -f '[i]ii compose --up' >/dev/null \
			|| { echo "the daemon exited: tail $(LOGS)/compose.log"; exit 1; }; \
		printf '.'; sleep 2; \
	done
	@echo ""
	@$(MAKE) --no-print-directory status

down: stop

# Every worker, same engine, in dependency order. A changed `engine:` section
# cannot be applied this way and says so: `ENGINE_RESTART_REQUIRED` means
# `make down && make up`.
restart:
	@iii trigger compose::restart --port $(MGR_PORT) --timeout-ms 600000

# Per-worker stdout and stderr, retained by the daemon. The daemon's own output
# — the engine's boot, and anything that failed before a worker existed — is in
# $(LOGS)/compose.log.
logs:
	@iii compose logs --follow

# ---------------------------------------------------------------- doing work

# One turn, with what a job's turn gets: the same settings, the same grants, the
# same callbacks. No factory, no worktree, no pull request.
turn:
	@test -n "$(PHASE)" || { echo 'usage: make turn PHASE=plan PROMPT="..." [WORKSPACE=../repo]'; exit 2; }
	@$(RUN) $(PY) scripts/turn.py \
		--phase '$(PHASE)' --prompt '$(PROMPT)' --workspace '$(WORKSPACE)'

# Step three, under whichever name you reached for. Work enters as a spec or as
# an idea, and both are the factory.
work:
	@echo "work enters the factory one of two ways:"
	@echo '  make submit SPEC=specs/x.md REPO=../repo SLUG=owner/name'
	@echo '  make idea IDEA="a rough sentence" REPO=../repo'
	@exit 2

# ---------------------------------------------------------------- improving it

# Read what went wrong and propose what would have prevented it. Reads the audit
# log and the job records, sends one turn, stages what comes back.
#
# **It applies nothing.** A clean record produces no proposals rather than
# inventing three, so an empty answer here is the lane working.
improve:
	@$(MAKE) --no-print-directory call FN=ghola::improve JSON='{"repo":"$(REPO)"}'

proposals:
	@$(MAKE) --no-print-directory call FN=ghola::proposals JSON='{"run":"$(RUN)"}'

# Writes a spec into specs/ and stops. That spec goes through the same pipeline
# and the same pull request as any other work — `make submit SPEC=…`.
accept:
	@test -n "$(RUN)" || { echo 'usage: make accept RUN=abc123 N=0'; exit 2; }
	@$(MAKE) --no-print-directory call FN=ghola::accept \
		JSON='{"run":"$(RUN)","proposal":$(or $(N),0)}'

# Read out of the `audit-log` container's own environment, so the reader and the
# writer cannot drift apart. It used to be declared twice.
AUDIT_KINDS = $(shell sed -n 's/^ *AUDIT_LOG_KINDS: *//p' worker-compose.yaml)

# The append-only record: whether it is intact, and what it says.
# `VERIFY=1` exits non-zero on a broken chain, for a cron job or a CI step.
# Reads the log directly: a reader needs no worker, and asking the writer
# whether its own writing is intact is the wrong shape.
audit:
	@AUDIT_LOG_KINDS='$(AUDIT_KINDS)' AUDITLOG=$(AUDITLOG) $(PY) scripts/audit.py

# A default nobody can see is a magic number.
config:
	@GHOLA_ROOT=$(PWD) $(PY) scripts/config.py $(PHASE)

# ---------------------------------------------------------------- checking

test:
	@$(PY) -m unittest discover -s tests -p 'test_*.py' -v

test-live:
	@test -d tests/live || { echo "no tests/live yet — see PLAN.md section 7"; exit 1; }
	@$(RUN) $(PY) -m unittest discover -s tests/live -p 'test_*.py' -v

# A/B evaluations through the stock `eval` worker. ghola writes no runner: each
# file in evals/ is an eval::start request. Costs money, so nothing runs these
# on a timer until somebody asks.
eval:
	@$(PY) scripts/eval.py

# ---------------------------------------------------------------- asking

# A mesh function is not an HTTP endpoint, so `curl` cannot reach one. This is
# the only way to read what the platform thinks. `iii trigger` takes `key=value`
# tokens or `--json`, never `--payload`: the wrong spelling fails with an
# argument error that reads like the function is missing.
call:
	@test -n "$(FN)" || { echo "usage: make call FN=harness::status [JSON='{...}']"; exit 2; }
	@iii trigger $(FN) $(if $(JSON),--json '$(JSON)',) --port $(MGR_PORT)

schema:
	@test -n "$(FN)" || { echo "usage: make schema FN=harness::send"; exit 2; }
	@iii trigger $(FN) --help --port $(MGR_PORT)

# The catalogue the phase settings name their models from. An empty list here
# means the engine was started without credentials in scope.
models:
	@$(MAKE) --no-print-directory call FN=router::models::list

console:
	@echo "http://127.0.0.1:$(CONSOLE_PORT)"

# ---------------------------------------------------------------- lifecycle

# The daemon knows the state of every container it started, so this asks it
# rather than guessing from `pgrep` patterns that had to be bracketed to avoid
# matching the shell that went looking for them.
status:
	@iii trigger compose::status --port $(MGR_PORT) 2>/dev/null | python3 scripts/status.py \
		|| echo "compose is down — make up"
	@echo "ladder   : $(call provider,$(LADDER))"
	@echo "record   : $(call provider,$(AUDITLOG))"
	@# The engine's own listeners. These are `engine.workers`, not containers, so
	@# they do not appear above.
	@for p in $(STREAM_PORT) $(MGR_PORT) $(GOVERNED_PORT); do \
		printf 'port %-5s: %s\n' "$$p" "$$(lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1 && echo listening || echo free)"; \
	done

# One call: every container in reverse dependency order, then the engine, then
# the daemon exits. It replaced five `pkill -f` patterns, and pkill was the
# wrong tool — it matches on the command line rather than on the directory, so
# a second clone of this repository went down with this one.
stop:
	@iii trigger compose::stop --port $(MGR_PORT) 2>/dev/null || echo "compose was not running"
	@# The daemon answers first and exits after, and the engine is the last thing
	@# it stops, so the manager port going free is the whole stack being down.
	@for i in $$(seq 1 30); do \
		lsof -nP -iTCP:$(MGR_PORT) -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 1; \
	done
	@$(MAKE) --no-print-directory status

clean:
	@rm -rf $(LOGS)
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "removed $(LOGS) and __pycache__ (the venv is kept; use `rm -rf .venv`)"
