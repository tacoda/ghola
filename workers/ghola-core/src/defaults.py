"""What ghola does when nobody has configured it.

**Configuration is optional.** ghola runs with an empty `settings/`, or with
no `settings/` at all, and every file in it overrides a default stated here
rather than supplying something that was missing. A team that agrees with these
numbers writes nothing.

Convention is the other half. The tools below are stock iii functions, not
ghola's: the `coder` worker ships reading, searching, listing and editing, and
`shell` ships execution. A tool ghola wrote would be a tool the framework
already has, and rung 1 works the same over a function id whoever registered it.

The three ways to change any of this, in order of how much I want you to reach
for them:

1. a key in `settings/phases.yaml`, which overrides one value here
2. a whole phase block, which overrides the defaults for that phase
3. a Python module in an escape-hatch directory, when it is genuinely a judgment
"""

# The agent's surface is a discovery loop: list the functions, read a contract,
# call it. Rung 1 gates discovery as well as use, so a phase given tools and not
# the ability to read their contracts has been given nothing.
DISCOVERY = ["engine::functions::list", "engine::functions::info"]

# Reading, from the stock `coder` worker. `coder::read-file` is window-first and
# returns text inline; `shell::fs::read` returns a channel handle meant for
# binary payloads, and handing a model the handle version is how a turn spends
# three steps learning it cannot read a file.
READ_ONLY = DISCOVERY + [
    "coder::read-file",
    "coder::search",
    "coder::list-folder",
    "coder::tree",
    "coder::info",
]

# Editing, also stock. A check is never handed these, which is the whole of
# "checks do not repair": rung 1 leaves nothing to refuse and nothing to argue
# past, so the rule needs no predicate.
EDITING = ["coder::create-file", "coder::update-file", "coder::delete-file", "coder::move"]

# Running things. `shell::exec_bg` and `shell::status` are what let a turn start
# a test suite and poll it rather than blocking a step on it.
RUNNING = ["shell::exec", "shell::exec_bg", "shell::status", "shell::list"]

# The charter surfaces a repository ships, served by the stock `directory`
# worker rather than read by a tool of ours.
CHARTER = ["directory::skills::list", "directory::skills::get",
           "directory::prompts::list", "directory::prompts::get"]

PHASES = {
    # Read-only, on the thinking model. Deciding what to build and building it
    # are separate turns: the strong model is spent once, on the decision with
    # the largest blast radius, and spent after reading the repository so the
    # plan names real files rather than plausible ones.
    "plan": {
        "model": "claude-opus-5",
        "thinking_level": "high",
        "max_turns": 50,
        "functions": {"allow": READ_ONLY + CHARTER},
    },
    # Where the tokens actually go.
    "run": {
        "thinking_level": "xhigh",
        "max_turns": 80,
        "functions": {"allow": READ_ONLY + EDITING + RUNNING + CHARTER + ["harness::spawn"]},
    },
    # Runs the software and reports what it saw. May run, may not repair.
    "prove": {
        "max_turns": 50,
        "functions": {"allow": READ_ONLY + RUNNING + CHARTER},
    },
    # Reads the diff and stamps a verdict. May read around the change to learn
    # the repository's conventions; may not quietly fix what it finds.
    "review": {
        "thinking_level": "high",
        "max_turns": 50,
        "functions": {"allow": READ_ONLY + CHARTER},
    },
    # A vague idea becomes a spec work can begin from. Read-only against the
    # target repository: it decides what to ask for, not what to change.
    "refine": {
        "model": "claude-opus-5",
        "thinking_level": "high",
        "max_turns": 40,
        "functions": {"allow": READ_ONLY + CHARTER},
    },
}

DEFAULTS = {
    "model": "claude-sonnet-5",
    "thinking_level": "medium",
    "max_turns": 50,
    "functions": {"allow": READ_ONLY},
}


def config() -> dict:
    """The built-in configuration, in the shape `settings/phases.yaml` uses.

    Returned as a fresh copy, because a caller that merges into it would edit
    the defaults for every later caller in the process.
    """
    return {
        "defaults": {**DEFAULTS, "functions": {"allow": list(READ_ONLY)}},
        "phases": {name: dict(block) for name, block in PHASES.items()},
    }


# --------------------------------------------------------------- the pipeline

# The stage graph a factory runs when `settings/pipeline.yaml` is absent. A team
# that wants a different flow of work edits that file; this is what they are
# editing a copy of.
#
# The shape is wipp's, which earned it against three real repositories: plan on
# a thinking model, run on a cheap one, prove that it works, review the diff,
# publish, and then wait for a person. Nothing merges itself.
PIPELINE = {
    "first": "prepare",
    "terminal": ["landed", "closed", "failed"],
    "stages": {
        "prepare": {
            "action": "prepare_workspace",
            "next": "refine",
        },
        # Optional, and off unless a job asks for it. A spec somebody wrote
        # carefully should not be rewritten by a turn; an idea somebody typed in
        # a hurry has to become one before anything can be built from it.
        #
        # `make submit SPEC=... REFINE=1`, or `idea:` instead of `spec:`.
        "refine": {
            "phase": "refine",
            "opt_in": True,
            "requires": ["spec"],
            "produces": ["spec"],
            "skip_when": ["revision", "rework"],
            "next": "plan",
        },
        # Deciding what to build and building it are separate turns on different
        # models. The strong model is spent once, on the decision with the
        # largest blast radius, and spent AFTER reading the repository so the
        # plan names real files rather than plausible ones.
        "plan": {
            "phase": "plan",
            "requires": ["spec"],
            "produces": ["plan"],
            # A gate's complaint and a reviewer's comment are already briefs.
            # Re-planning would only blur them.
            "skip_when": ["revision", "rework"],
            # A plan turn that fails does not fail the job; it hands over an
            # empty plan.
            "on_error": "continue",
            "next": "run",
        },
        "run": {
            "phase": "run",
            # Not `plan`: planning is skipped for a revision, and requiring it
            # would make every revision unable to start.
            "requires": ["spec"],
            "produces": ["work"],
            "on_refusal": {"goto": "run", "max": 2, "stop_when_identical": True},
            "next": "prove",
        },
        # Runs the software against the spec while the environment is still up.
        # The worktree is checked afterwards and anything a check changed is
        # reverted, because a shell can write whatever its tool list says.
        "prove": {
            "phase": "prove",
            "requires": ["work"],
            "produces": ["proof"],
            "optional": True,
            "contract": "proven",
            "revert_worktree_changes": True,
            "next": "review",
        },
        # Handed the spec and the diff, and nothing else. Never the executor's
        # summary of its own work: a check fed the work's own account of itself
        # is grading a story.
        "review": {
            "phase": "review",
            "requires": ["work"],
            "produces": ["review"],
            "optional": True,
            "contract": "verdict",
            "next": "commit",
        },
        # Rung 4, the repository's own commit hook, then the branch. A refusal
        # here goes back to `run` with the gate's own words as the brief.
        "commit": {
            "action": "commit_and_push",
            "on_refusal": {"goto": "run", "max": 2, "stop_when_identical": True},
            "next": "publish",
        },
        "publish": {
            "action": "open_pull_request",
            "next": "waiting",
        },
        # ghola opens a pull request and stops. A human merges, and what they
        # do is the edge out of here.
        "waiting": {
            "action": "watch_pull_request",
            "on_merge": "landed",
            "on_close": "closed",
            "on_comment": "rework",
        },
        "rework": {
            "action": "prepare_workspace",
            "next": "run",
        },
    },
}


def pipeline() -> dict:
    """The built-in stage graph, as a fresh copy."""
    import copy
    return copy.deepcopy(PIPELINE)
