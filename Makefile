# ghola. `make` is the whole operator surface: there is no CLI to learn.
#
# Three steps, and `make setup` is step one:
#
#   1. clone the repo          git clone … && make setup
#   2. add config and scripts  edit settings/, drop files in actions/
#   3. tell it to do work      make turn  (make work, once the factory lands)

.PHONY: help setup doctor install engine policy ladder factory auditd submit up down logs status stop restart \
        call schema models console config pipeline jobs turn idea work test test-live eval audit clean

VENV := .venv
PY   := $(VENV)/bin/python
LOGS := .logs

HTTP_PORT    := 3131
CONSOLE_PORT := 3133
STREAM_PORT  := 3132
MGR_PORT     := 49154
GOVERNED_PORT := 49155

# `.env` is sourced for the ENGINE, not only for the workers. The provider
# workers read their credentials from the engine's own environment, so an engine
# started without them serves a router with no models and every turn fails at
# `router::provider::resolve` with nothing saying why.
ENV := set -a; [ -f .env ] && . ./.env; set +a;
RUN := $(ENV) PYTHONUNBUFFERED=1 GHOLA_ROOT=$(PWD) III_URL=ws://localhost:$(MGR_PORT)

help:
	@echo "getting started"
	@echo "  make setup      everything a fresh clone needs, then says what is next"
	@echo "  make doctor     what is missing, before you waste a turn finding out"
	@echo ""
	@echo "running it"
	@echo "  make up         engine and policy worker, in the background"
	@echo "  make down       all of it, and wait for the ports to free"
	@echo "  make status     what is up"
	@echo "  make logs       tail what is running"
	@echo ""
	@echo "doing work"
	@echo '  make turn PHASE=plan PROMPT="..." [WORKSPACE=../repo]'
	@echo "  make config     the effective settings, and where each value came from"
	@echo "  make pipeline   the stage graph as it will run, and what is wrong with it"
	@echo '  make submit SPEC=specs/x.md REPO=../repo SLUG=owner/name'
	@echo '  make idea IDEA="a rough sentence" REPO=../repo   # refined into a spec first'
	@echo "  make jobs       every job, newest first"
	@echo "  make audit      the append-only record: intact? and what it says"
	@echo "  make models     what the router can actually reach"
	@echo ""
	@echo "checking it"
	@echo "  make test       pure and worker tests. Seconds, no engine, no money"
	@echo "  make test-live  framework contract tests. Needs a running engine"
	@echo "  make eval       A/B evals through the eval worker. Costs money"
	@echo ""
	@echo "asking the engine"
	@echo "  make call FN=harness::status [JSON='{...}']"
	@echo "  make schema FN=harness::send"

# ---------------------------------------------------------------- step one

# Everything a fresh clone needs, in the order it needs it. Idempotent: running
# it again after adding a dependency is the supported way to install one.
setup: doctor install
	@[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "  wrote .env from the example"; }
	@echo ""
	@echo "ready. Next:"
	@echo "  1. put your ANTHROPIC_API_KEY in .env"
	@echo "  2. make up"
	@echo '  3. make turn PHASE=plan PROMPT="what does this repo do?"'

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
	@printf '  %-9s ' "harness"; \
		grep -A1 '^  harness:' iii.lock 2>/dev/null | grep version | sed 's/.*version: //' \
		|| echo "not pinned — run: iii worker add harness"
	@printf '  %-9s ' ".env"; \
		{ [ -f .env ] && grep -q '^ANTHROPIC_API_KEY=.\+' .env && echo "ANTHROPIC_API_KEY set"; } \
		|| echo "no ANTHROPIC_API_KEY yet"
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
	@for slug in $$(grep -oE 'slug *= *"[^"]+"' repos.toml 2>/dev/null | grep -oE '"[^"]+"' | tr -d '"'); do \
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
	@uv pip install --quiet --python $(PY) -e workers/ghola-core -e workers/ghola-policy -e workers/ghola-factory -e workers/ghola-audit
	@echo "  installed ghola-core, ghola-policy, ghola-factory and ghola-audit into $(VENV)"

# ---------------------------------------------------------------- running

# The console's port is a startup seed the engine consumes and comments out of
# config.yaml on every boot, so it is put back first. Without this the console
# silently returns to the stock 3113 and loses to whatever is already there.
engine:
	@python3 scripts/seed_console_port.py
	@$(ENV) iii --config config.yaml

# The ladder, as a HOST process rather than a managed worker.
#
# `iii worker add ../ladder` runs it in a microVM with only its own source
# mounted, and the target repository does not exist inside that sandbox: it
# reads a `.claude/settings.json` from a path that is not there and reports a
# repository with no permissions, which looks exactly like permissions that are
# not enforced. Anything that inspects a target repo has to run where that repo
# is.
LADDER ?= ../ladder

ladder:
	@test -d $(LADDER) || { echo "no ladder at $(LADDER). Clone tacoda/ladder beside this repo"; exit 2; }
	@$(ENV) PYTHONUNBUFFERED=1 III_URL=ws://localhost:$(MGR_PORT) LADDER_HOME=$(LADDER) \
		$(LADDER)/.venv/bin/python $(LADDER)/src/main.py

# One process owns the append-only chain. Two writers interleave their `prev`
# hashes and produce a log that fails its own verification while nothing has
# tampered with it, so this starts BEFORE the workers that record.
auditd:
	@$(RUN) $(PY) workers/ghola-audit/src/audit_worker.py

# The pipeline. Serves no HTTP: the console is the UI.
factory:
	@$(RUN) $(PY) workers/ghola-factory/src/factory.py

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

# What this repository contributes to a turn: four callbacks and no tools. The
# turn loop is the harness worker's, started by the engine like every other one.
policy:
	@$(RUN) $(PY) workers/ghola-policy/src/boot.py

# Both, backgrounded, because remembering two foreground terminals is a thing to
# remember rather than a design. `make logs` is how you watch them.
up:
	@mkdir -p $(LOGS)
	@pgrep -f '[i]ii --config config.yaml' >/dev/null || { \
		python3 scripts/seed_console_port.py; \
		($(ENV) iii --config config.yaml > $(LOGS)/engine.log 2>&1 &); \
		printf 'starting engine '; }
	@for i in $$(seq 1 90); do \
		lsof -nP -iTCP:$(MGR_PORT) -sTCP:LISTEN >/dev/null 2>&1 && break; printf '.'; sleep 1; \
	done
	@# The workers are the engine's children and register over the following
	@# minute. Starting the policy worker before the harness is up binds nothing,
	@# and a hook that is not bound looks exactly like one that is.
	@#
	@# The probe is `router::provider::list`, NOT `harness::status`: that one
	@# requires a session_id and fails with a serialization error, so this loop
	@# ran all ninety seconds on every single boot and called it waiting.
	@for i in $$(seq 1 90); do \
		iii trigger router::provider::list --port $(MGR_PORT) >/dev/null 2>&1 && break; \
		printf '.'; sleep 1; \
	done
	@echo ""
	@# Before the recorders, so their first entry has somewhere to go.
	@pgrep -f '[g]hola-audit/src/audit_worker.py' >/dev/null \
		|| ($(RUN) $(PY) workers/ghola-audit/src/audit_worker.py > $(LOGS)/audit.log 2>&1 &)
	@sleep 2
	@pgrep -f '[g]hola-policy/src/boot.py' >/dev/null \
		|| ($(RUN) $(PY) workers/ghola-policy/src/boot.py > $(LOGS)/policy.log 2>&1 &)
	@pgrep -f '[g]hola-factory/src/factory.py' >/dev/null \
		|| ($(RUN) $(PY) workers/ghola-factory/src/factory.py > $(LOGS)/factory.log 2>&1 &)
	@test -d $(LADDER) && { pgrep -f '[l]adder/src/main.py' >/dev/null \
		|| ($(ENV) PYTHONUNBUFFERED=1 III_URL=ws://localhost:$(MGR_PORT) LADDER_HOME=$(LADDER) \
		    $(LADDER)/.venv/bin/python $(LADDER)/src/main.py > $(LOGS)/ladder.log 2>&1 &); } || true
	@sleep 4
	@$(MAKE) --no-print-directory status

down: stop

restart:
	@$(MAKE) --no-print-directory stop
	@$(MAKE) --no-print-directory up

logs:
	@tail -n 40 -f $(LOGS)/*.log

# ---------------------------------------------------------------- doing work

# One turn, with what a job's turn gets: the same settings, the same grants, the
# same callbacks. No factory, no worktree, no pull request.
turn:
	@test -n "$(PHASE)" || { echo 'usage: make turn PHASE=plan PROMPT="..." [WORKSPACE=../repo]'; exit 2; }
	@$(RUN) $(PY) scripts/turn.py \
		--phase '$(PHASE)' --prompt '$(PROMPT)' --workspace '$(WORKSPACE)'

# Step three. The factory arrives in M4; until then this says so rather than
# failing with an import error.
work:
	@echo "the factory arrives in M4. Until then, one turn at a time:"
	@echo '  make turn PHASE=plan PROMPT="..." WORKSPACE=../repo'
	@exit 2

# The append-only record: whether it is intact, and what it says.
# `VERIFY=1` exits non-zero on a broken chain, for a cron job or a CI step.
# Reads the log directly: a reader needs no worker, and asking the writer
# whether its own writing is intact is the wrong shape.
audit:
	@$(PY) scripts/audit.py

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

# The bracket in `[i]ii` is load-bearing: `pgrep -f` matches on the full command
# line, and the subshell running the pattern has the pattern in its own command
# line. Without the bracket this target reports "up" forever, including with
# every port free.
status:
	@echo "engine   : $$(pgrep -f '[i]ii --config config.yaml' >/dev/null && echo up || echo down)"
	@echo "policy   : $$(pgrep -f '[g]hola-policy/src/boot.py' >/dev/null && echo up || echo down)"
	@echo "ladder   : $$(pgrep -f '[l]adder/src/main.py' >/dev/null && echo up || echo down)"
	@echo "factory  : $$(pgrep -f '[g]hola-factory/src/factory.py' >/dev/null && echo up || echo down)"
	@echo "audit    : $$(pgrep -f '[g]hola-audit/src/audit_worker.py' >/dev/null && echo up || echo down)"
	@for p in $(HTTP_PORT) $(CONSOLE_PORT) $(STREAM_PORT) $(MGR_PORT) $(GOVERNED_PORT); do \
		printf '%-9s: %s\n' "port $$p" "$$(lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1 && echo listening || echo free)"; \
	done

# `pkill -f` matches on the command line, not on the directory, so a second
# clone of this repository running its own engine goes down with this one.
# Run `make status` first if more than one is up.
#
# `|| true` because pkill exits 1 when nothing matched, and stopping what is
# already stopped is a success here rather than an error to read past.
stop:
	@pkill -f 'ghola-policy/src/boot.py' || true
	@pkill -f 'ghola-factory/src/factory.py' || true
	@pkill -f 'ghola-audit/src/audit_worker.py' || true
	@pkill -f 'ladder/src/main.py' || true
	@pkill -f 'iii --config config.yaml' || true
	@# The engine's workers are its children and outlive the signal by a few
	@# seconds. A fixed sleep reported them still up, which is the opposite of
	@# what this target is for, so it waits for the ports instead.
	@for i in $$(seq 1 30); do \
		lsof -nP -iTCP:$(HTTP_PORT),$(CONSOLE_PORT),$(MGR_PORT) -sTCP:LISTEN >/dev/null 2>&1 || break; \
		sleep 1; \
	done
	@$(MAKE) --no-print-directory status

clean:
	@rm -rf $(LOGS)
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "removed $(LOGS) and __pycache__ (the venv is kept; use `rm -rf .venv`)"
