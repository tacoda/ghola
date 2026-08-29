.PHONY: engine status stop call models console help test test-live eval

# `.env` is sourced for the ENGINE, not only for the workers. The provider
# workers read their credentials from the engine's own environment, so an engine
# started without them serves a router with no models and every turn fails at
# `router::provider::resolve` with nothing saying why.
ENV := set -a; [ -f .env ] && . ./.env; set +a;

HTTP_PORT    := 3131
CONSOLE_PORT := 3133
MGR_PORT     := 49154

help:
	@echo "make engine    # the engine and its workers (foreground)"
	@echo "make status    # what is up"
	@echo "make stop      # all of it down, and wait for the ports to free"
	@echo "make call FN=harness::status [PAYLOAD='{...}']"
	@echo "make models    # what the router can actually reach"
	@echo "make test      # pure and worker tests. Seconds, no engine, no money."
	@echo "make test-live # framework contract tests. Needs a running engine."
	@echo "make eval      # phase evals. Needs an engine, and costs money."

# Three commands rather than one, because they cost three different things.
# Only this one is cheap enough to be a pre-commit gate; a gate nobody can
# afford to run is a gate that gets skipped.
test:
	@python3 -m unittest discover -s tests -p 'test_*.py' -v

test-live:
	@test -d tests/live || { echo "no tests/live yet — see PLAN.md section 7"; exit 1; }
	@python3 -m unittest discover -s tests/live -p 'test_*.py' -v

eval:
	@test -d evals || { echo "no evals/ yet — see PLAN.md section 4.8"; exit 1; }
	@$(MAKE) --no-print-directory call FN=ghola::eval::run \
		PAYLOAD='{"case": "$(CASE)"}'

# The console's port is a startup seed the engine consumes and comments out of
# config.yaml on every boot, so it is put back first. Without this the console
# silently returns to the stock 3113 and loses to whatever is already there.
engine:
	@python3 scripts/seed_console_port.py
	@$(ENV) iii --config config.yaml

# A mesh function is not an HTTP endpoint, so `curl` cannot reach one. This is
# the only way to read what the platform thinks.
call:
	@test -n "$(FN)" || { echo "usage: make call FN=harness::status [PAYLOAD='{...}']"; exit 2; }
	@iii trigger $(FN) $(if $(PAYLOAD),--payload '$(PAYLOAD)',) --port $(MGR_PORT)

# The catalogue the phase settings name their models from. An empty list here
# means the engine was started without credentials in scope.
models:
	@$(MAKE) --no-print-directory call FN=router::models::list

console:
	@iii worker restart console

# The bracket in `[i]ii` is load-bearing: `pgrep -f` matches on the full command
# line, and the subshell running the pattern has the pattern in its own command
# line. Without the bracket this target reports "up" forever, including with
# every port free.
status:
	@echo "engine   : $$(pgrep -f '[i]ii --config config.yaml' >/dev/null && echo up || echo down)"
	@for p in $(HTTP_PORT) $(CONSOLE_PORT) $(MGR_PORT); do \
		printf '%-9s: %s\n' "port $$p" "$$(lsof -nP -iTCP:$$p -sTCP:LISTEN >/dev/null 2>&1 && echo listening || echo free)"; \
	done

# `pkill -f` matches on the command line, not on the directory, so a second
# clone of this repository running its own engine goes down with this one.
# Run `make status` first if more than one is up.
#
# `|| true` because pkill exits 1 when nothing matched, and stopping what is
# already stopped is a success here rather than an error to read past.
stop:
	@pkill -f 'iii --config config.yaml' || true
	@# The engine's workers are its children and outlive the signal by a few
	@# seconds. A fixed sleep reported them still up, which is the opposite of
	@# what this target is for, so it waits for the ports instead.
	@for i in $$(seq 1 25); do \
		lsof -nP -iTCP:$(HTTP_PORT),$(CONSOLE_PORT),$(MGR_PORT) -sTCP:LISTEN >/dev/null 2>&1 || break; \
		sleep 1; \
	done
	@$(MAKE) --no-print-directory status
