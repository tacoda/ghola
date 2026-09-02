"""The built-in stage actions: what a stage does when it is not running a turn.

Every one of these is a thin call to a stock worker. ghola runs no git and talks
to no forge directly, which is the whole reason this file is short:

| action | what it actually calls |
|---|---|
| `prepare_workspace` | `worktree::create` and `worktree::claim`, then `shell::exec` |
| `open_pull_request` | whatever the forge driver names |
| `watch_pull_request` | whatever the forge driver names |
| `teardown` | `shell::exec`, then `worktree::release` |

An action returns the same shape a turn does — `{ok, refused, blocked, outcome,
error}` — so `graph.next_stage` does not care which kind of stage it just ran.
That symmetry is what keeps the state machine a pure function of two dicts.

**No forge is named in this file.** Which calls open a request and read it back
is `forge.py`'s answer, and it is pure: a driver returns the calls and reads the
answers, and `perform` below is the only thing that makes one.
"""

from __future__ import annotations

import os
from pathlib import Path

import diffs
import extensions
import forge as forgelib
import governance
import jobs
import publishing

ROOT = Path(os.environ.get("GHOLA_ROOT", Path(__file__).resolve().parents[3]))


def call(worker, function_id: str, payload: dict, timeout_ms: int = 120000) -> dict:
    """One function on the bus, with the governance gate in front of it.

    **Every outbound call from the factory passes here**, which is the point: a
    promote-class call that skipped this would be a call that shipped something
    without proving it, and the gate would be decoration.
    """
    gate = governance.decide(function_id, has_verdict=bool(payload.pop("_verdict", False)))
    if not gate.allowed:
        return {"ok": False, "governance": gate.decision, "error": gate.reason}

    try:
        answer = worker.trigger({"function_id": function_id,
                                 "timeout_ms": timeout_ms,
                                 "payload": payload}) or {}
        return {"ok": True, "value": answer.get("payload") or answer}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{function_id}: {type(exc).__name__}: {exc}"}


def run(worker, program: str, args: list[str], cwd: str, env: dict | None = None,
        timeout_ms: int = 300000) -> dict:
    """One program, with its arguments. **`shell::exec` is not a shell.**

    It spawns a program directly: `command` is the program name and `args` is a
    list. Passing `git add -A && git commit -m x` as `command` tries to spawn a
    program with that literal name, which fails with S216 and — because the
    caller was only catching exceptions — looked like a commit that worked. The
    first job through the rework test pushed a branch with no commits on it.

    **A non-zero exit is a failure.** `shell::exec` returns `exit_code` in its
    payload rather than raising, so a command that ran and failed comes back
    `ok`. That is the shape the repository's own commit hook refusing takes, and
    reading it as success would silently disable the whole revision loop.
    """
    answer = call(worker, "shell::exec",
                  {"command": program, "args": list(args), "cwd": cwd,
                   "env": env or {}}, timeout_ms=timeout_ms)
    if not answer["ok"]:
        return answer

    value = answer["value"]
    code = int(value.get("exit_code") or 0)
    output = f"{value.get('stdout') or ''}{value.get('stderr') or ''}".strip()
    if code != 0:
        return {"ok": False, "exit_code": code, "output": output,
                "error": output or f"`{program}` exited {code}"}
    return {"ok": True, "output": output, "value": value}


def run_command(worker, command: str, cwd: str, env: dict | None = None,
                timeout_ms: int = 600000) -> dict:
    """A repository's own command line, which may use shell syntax.

    `prepare = "make up && make migrate"` is a shell string a person wrote, so
    it gets a shell — explicitly, through `sh -c`, rather than by hoping the
    exec surface provides one. An empty command is a success rather than a no-op
    error: most repositories need neither.
    """
    if not command.strip():
        return {"ok": True, "value": {"skipped": "no command configured"}}
    return run(worker, "sh", ["-c", command], cwd, env, timeout_ms)


# ------------------------------------------------------------ the actions

def prepare_workspace(worker, job: dict, settings: dict) -> dict:
    """Claim an isolated worktree, then run the repository's prepare command.

    The worktree is the `worktree` worker's, including the claim that stops two
    jobs racing for one checkout: `worktree::claim` fails with `W210` when
    another session holds it, and that is the concurrency answer rather than a
    semaphore of ours.

    A rework re-runs prepare, because the environment was torn down when the
    pull request opened and a reviewer's comment can arrive days later.
    """
    repo = settings.get("repo_settings") or {}
    existing = job.get("worktree_id")

    if existing:
        claimed = call(worker, "worktree::claim",
                       {"worktree_id": existing, "session_id": job["id"]})
        if not claimed["ok"]:
            return {"ok": False, "error": f"could not reclaim the worktree: "
                                          f"{claimed.get('error')}"}
        path = job.get("workspace", "")
    else:
        # The branch name is ghola's, from `repos.toml`. Without it the
        # worktree worker names the branch `<its own prefix><worktree_id>`, and
        # a repository whose CONTRIBUTING says `feature/` gets `iii/wt_ab12cd`
        # with nothing reporting that its convention was ignored.
        made = call(worker, "worktree::create", {
            "repo_path": job.get("repo") or repo.get("path"),
            "session_id": job["id"],
            "branch": branch_name(job, repo),
            **({"base_ref": repo["base"]} if repo.get("base") else {}),
        })
        if not made["ok"]:
            return {"ok": False, "error": f"could not mint a worktree: "
                                          f"{made.get('error')}"}
        value = made["value"]
        path = str(value.get("path") or "")
        job["worktree_id"] = value.get("worktree_id")
        job["workspace"] = path
        job["branch"] = value.get("branch")

    prepared = run_command(worker, str(repo.get("prepare") or ""), path,
                           dict(repo.get("env") or {}))
    if not prepared["ok"]:
        # A repository whose stack will not come up cannot be worked on, and
        # finding out here is far cheaper than finding out at the commit gate
        # after a paid turn.
        return {"ok": False, "error": f"prepare failed: {prepared.get('error')}"}

    return {"ok": True, "workspace": path, "worktree_id": job.get("worktree_id")}


def branch_name(job: dict, repo: dict) -> str:
    """The branch this job works on, from the repository's own convention.

    A slug from the spec's title, so a person reading a list of branches on the
    forge can tell which is which, **and a short job id so re-running the same
    spec does not collide**. Without the suffix the second run of any spec fails
    at `worktree::create` with `W120: branch already exists`, which is a real
    failure wearing a confusing message.

    A rework reuses the worktree it already has, so this runs once per job and
    uniqueness per job is the right grain.
    """
    import re
    title = str(job.get("title") or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", title).strip("-")[:40].strip("-")
    prefix = str(repo.get("branch_prefix") or "ghola/")
    short = str(job.get("id", ""))[:8] or "job"
    return f"{prefix}{slug}-{short}" if slug else f"{prefix}{short}"


def commit_and_push(worker, job: dict, settings: dict) -> dict:
    """Rung 4, then the commit, then the branch. Nothing merges.

    Three things happen here and the order is the point.

    **The delivery gate first.** Rung 4 sees two things no other rung can: the
    finished diff, and *what the job is about to publish*. A commit message and
    a pull request body are neither written by a tool nor part of any diff, so
    nothing below rung 4 has ever seen them.

    **Then the repository's own commit hook**, which runs inside `git commit`
    and is the target repository's say. Its refusal becomes the brief for
    another turn, verbatim rather than summarised, because the gate's own words
    are the most useful thing anyone has said about the work.

    **Then the push.** `worktree::land` is deliberately not used: it
    fast-forwards the target branch, and ghola opens a pull request and stops.
    """
    workspace = str(job.get("workspace") or "")
    branch = str(job.get("branch") or "")
    if not workspace or not branch:
        return {"ok": False, "error": "no worktree to commit from"}

    message = commit_message(job)

    # Stage whatever is loose, so the gate sees it whether the turn committed or
    # not. **The run phase can commit by itself**: it has `shell::exec` and
    # nothing withholds git from it, and the first rework run did exactly that.
    # A gate that only looked at staged changes would then see an empty diff and
    # wave through work it never read.
    run(worker, "git", ["add", "-A"], workspace)

    # Where the branch has to get to before anybody can look at it, which is the
    # forge's answer and not this stage's. A repository with no forge has no
    # remote at all, and every ref below has to name something that exists.
    driver, problem = driver_for(job, settings)
    if problem:
        return {"ok": False, "error": problem}
    remote = driver.remote
    against = base_ref(job, settings)

    # A refusal is the change's problem and routes to a rework. A gate that
    # could not answer is the job's problem: reworking a diff does not bring a
    # worker back up, and pretending it was allowed is how a gate fails open.
    refused, problem = rung_four(worker, job, workspace, message, against)
    if problem:
        return {"ok": False, "error": problem}
    if refused:
        return {"ok": True, "refused": True, "refusal": refused}

    committed = run(worker, "git", ["commit", "-m", message], workspace)
    already = "nothing to commit" in str(committed.get("output") or "")
    if not committed["ok"] and not already:
        # The repository's own hook refused. Verbatim, because summarising it
        # would throw away the only specific thing anybody said about the work.
        return {"ok": True, "refused": True,
                "refusal": str(committed.get("output") or "")[:4000]}

    # Nothing loose to commit is fine IF the turn already committed. What is not
    # fine is a branch with nothing on it at all.
    ahead = run(worker, "git", ["log", "--oneline", f"{against}..HEAD"], workspace)
    if ahead["ok"] and not str(ahead.get("output") or "").strip():
        return {"ok": False, "error": (
            "the turn finished and the branch has no commits on it, so there is "
            "nothing to publish")}

    if not remote:
        # Nowhere to push. The branch is already in the checkout the reviewer
        # will open, which is the whole of what `forge = "local"` means.
        return {"ok": True, "committed": True, "branch": branch, "pushed": False}

    pushed = run(worker, "git", ["push", "-u", remote, branch], workspace)
    if not pushed["ok"]:
        return {"ok": False, "error": f"push failed: {pushed.get('error')}"}

    return {"ok": True, "committed": True, "branch": branch, "pushed": True}


def commit_message(job: dict) -> str:
    """What the commit says.

    No AI attribution, and that is a rule rather than a preference: this
    repository's operator is the author, and a trailer naming a tool is
    something rung 4 refuses. It is not added here so it never has to be
    removed there.
    """
    # The same stripping the request title gets. A spec's first line is `# Do
    # the thing`, and the `#` was reaching the commit subject: `git commit -m`
    # keeps it, so every commit in the scratch repository read as a heading.
    return forgelib.title_of(job)[:72]


# Per file, where it used to be per whole diff. A file's patch this long is a
# generated lockfile or a vendored tree, so the bound stays generous and says
# when it bit. ponytail: one number for every repository. It becomes a setting
# the first time a real change trips it.
PER_FILE_LIMIT = 200000

# The whole-diff cut used to bound the work as a side effect: 200,000 characters
# was however many files that came to. Per file there is no such accident, so a
# vendored bump touching thousands of files would make thousands of calls at a
# 60-second timeout each. A change this wide is not a reviewable change, so the
# gate says so instead of grinding.
MAX_FILES = 500


def rung_four(worker, job: dict, workspace: str, text: str,
              against: str = "HEAD") -> tuple[str, str]:
    """The delivery gate, over the finished diff and the text about to ship.

    Returns `(refusal, problem)`, and an empty pair is the only outcome that
    reaches a commit. A **refusal** is the ladder saying no, which routes to a
    rework because the change is what has to alter. A **problem** is the gate
    unable to answer at all, which no rework fixes.

    **This gate fails closed**, and it did not before. An unreachable ladder
    returned "not refused", and so did a failed `git diff`, so a downed worker
    read exactly like a clean change. The ladder states the principle in its own
    predicate runner: a predicate that throws is a finding, not a pass.

    Asked of the `ladder` worker rather than reimplemented, so the same
    predicate that refuses a write at rung 3 refuses the finished file here.

    **One call per file.** Rung 4 used to pass no path, and an empty path skips
    the filter in `Loaded.governing` and in `gate.decide` both, so every
    path-scoped rule was asked about every file in the change and its findings
    could name none of them. A file is also the unit `check(path, content,
    context)` was written for.

    `text` is what the job is about to publish, and it goes with every file
    rather than once: `gate.escaped` reads an escape hatch out of the commit
    message, and a file evaluated without it would be refused by a rule the
    operator had already escaped.
    """
    # Everything not yet on the base, committed or not. `--cached` alone would
    # miss work the turn committed itself, which is the hole that let a diff
    # reach a branch without the delivery gate reading it. The ref is passed in
    # rather than assumed: `origin/main` does not resolve in a repository with
    # no remote, and the gate would then read the staged half of the work.
    parts = []
    for args in (["diff", f"{against}...HEAD", "--unified=0"],
                 ["diff", "--cached", "--unified=0"]):
        answer = run(worker, "git", args, workspace)
        if not answer["ok"]:
            return "", (f"the delivery gate could not read the change: `git "
                        f"{' '.join(args)}` failed: {answer.get('error')}")
        parts.append(str(answer.get("output") or ""))

    files = diffs.per_file("\n".join(parts))
    if len(files) > MAX_FILES:
        return "", (f"the delivery gate will not read {len(files)} files in one "
                    f"change, and the limit is {MAX_FILES}. Split it, or raise "
                    "MAX_FILES knowing every file costs a call to the ladder")

    # An empty diff still gets one evaluation. A rule about what a pull request
    # may say does not need a file to have been touched to be broken, and the
    # "no commits on the branch" error belongs to the caller rather than here.
    for path, patch in files or [("", "")]:
        content = publishing.trim(patch, PER_FILE_LIMIT)
        if len(patch) > PER_FILE_LIMIT:
            # Said out loud rather than swallowed. The marker `trim` leaves is
            # inside what the ladder reads, so a predicate sees the bound too.
            print(f"rung 4: {path} is {len(patch)} characters of diff and the "
                  f"gate read the first {PER_FILE_LIMIT}")

        answer = call(worker, "ladder::evaluate", {
            "repo": workspace,
            "path": path,
            "content": content,
            "publishing": text,
            "rung": 4,
        }, timeout_ms=60000)

        if not answer["ok"]:
            return "", (f"the delivery gate could not reach the ladder, so "
                        f"nothing has checked this change: {answer.get('error')}")

        body = answer["value"]
        if not body.get("allowed", True):
            return str(body.get("reason") or "refused"), ""

    return "", ""


def base_ref(job: dict, settings: dict | None = None) -> str:
    """The ref this job's work is diffed against.

    One derivation and two readers: the delivery gate at rung 4, and the brief
    the review phase is handed. A reviewer grading against a different ref than
    the gate reads is a reviewer whose `pass` means nothing at delivery, and
    keeping the two in one function is cheaper than keeping them in step.

    An unresolved driver degrades to the bare base rather than raising. The
    commit stage names the missing forge itself, and a review against the local
    branch is worth more than a brief that failed to render.

    ponytail: `driver_for` runs twice per commit stage, once here and once for
    the driver object the caller needs. It is a dict lookup for a built-in forge
    and a directory glob for a custom one, both once per job.
    """
    settings = settings or {}
    repo = job.get("repo_settings") or settings.get("repo_settings") or {}
    base = str(repo.get("base") or "") or "HEAD"
    driver, problem = driver_for(job, settings)
    remote = "" if problem else str(getattr(driver, "remote", "") or "")
    return f"{remote}/{base}" if remote else base


def driver_for(job: dict, settings: dict):
    """The forge this job delivers through, or an error naming what is missing.

    Resolved per job rather than per process, because `repos.toml` is per
    repository and one factory can serve a GitHub repo and a local one.
    """
    name = forgelib.for_job({**settings, **job})
    found = forgelib.named(name)
    if found is not None:
        return found, ""

    try:
        module, function_id = extensions.resolve(name, ROOT, "forges")
    except extensions.ExtensionError as exc:
        return None, str(exc)
    if module is None:
        return None, (f"`forge = \"{name}\"` names a function id, and a forge "
                      "driver is a module rather than one call. Put it in "
                      f"forges/{name}.py")
    return module, ""


def perform(worker, calls: list) -> tuple[list, dict]:
    """Make the calls a driver asked for. Returns the answers and the first
    failure that was not marked as tolerable.

    A driver says which of its calls may fail: GitHub's two comment endpoints
    are each optional because a repository can legitimately have neither kind,
    while the call that opens the request is not.
    """
    answers = []
    for one in calls:
        answer = call(worker, one["function_id"], dict(one["payload"]))
        answers.append(answer)
        if not answer["ok"] and not one.get("allow_failure"):
            return answers, answer
    return answers, {}


def open_pull_request(worker, job: dict, settings: dict) -> dict:
    """Publish the work for a human to decide on. ghola never merges.

    **Idempotent.** A rework pushes to the same branch, so the request that
    already exists updates itself and there is nothing to open. The first rework
    ran the whole loop correctly and then tried to create a second pull request
    for a branch that already had one.
    """
    driver, problem = driver_for(job, settings)
    if problem:
        return {"ok": False, "error": problem}

    if job.get("pr_number"):
        # Already open. Say on it that the answer has been pushed, so a reviewer
        # is not left watching a branch change with no explanation.
        answered = answer_pushed(worker, job)
        return {"ok": True, "pull_request": job.get("pull_request"),
                "pr_number": job["pr_number"],
                "reopened": False, "commented": answered["ok"]}

    missing = driver.ready({**settings, **job})
    if missing:
        return {"ok": False, "error": missing}

    # The first real job opened a pull request with an EMPTY body, which makes a
    # reviewer reconstruct what was asked and what was checked from the diff
    # alone. This is the document the phases built: the account of the work.
    body = publishing.pull_request_body(job, job.get("document") or "")
    answers, failed = perform(worker, driver.open_calls({**settings, **job}, body))
    if failed:
        return failed

    return {"ok": True, "forge": driver.name, **driver.opened(job, answers)}


def watch_pull_request(worker, job: dict, settings: dict) -> dict:
    """Read the request and report what the human did.

    Returns an `outcome` the graph turns into an edge: merge lands it, close
    closes it, a comment is a brief for another turn. **Nothing is a legitimate
    answer** and means the card waits.

    ghola tells its own comments from a reviewer's by a marker rather than by
    author, because it pushes with the operator's credentials and *is* the
    request's author.
    """
    driver, problem = driver_for(job, settings)
    if problem:
        return {"ok": False, "error": problem}
    if not job.get("pr_number"):
        return {"ok": False, "error": f"no {driver.noun} to watch"}

    seen, failed = perform(worker, driver.view_calls({**settings, **job}))
    if failed:
        return failed

    pr = dict(driver.state({**settings, **job}, seen))
    pr["comments"] = comments_on(worker, driver, job, settings, seen)
    return {"ok": True, **derive_outcome(job, pr)}


def comments_on(worker, driver, job: dict, settings: dict, seen: list) -> list[dict]:
    """Everything anybody said, from wherever this forge keeps it.

    A driver that reads its comments out of what `view` already returned asks
    for no further calls, and gets handed those answers instead: reading one
    file twice would be two reads of one thing.
    """
    calls = driver.comment_calls({**settings, **job})
    if not calls:
        return driver.comments(seen)
    answers, _ = perform(worker, calls)
    return driver.comments(answers)


def teardown(worker, job: dict, settings: dict) -> dict:
    """Run the repository's cleanup, then give the worktree back.

    **Called when a job reaches a terminal state**, not as a stage anybody
    routes to. A job that lands and keeps its worktree leaks one per job, and
    the first three real runs left three behind before anything called this.

    Every step is best-effort and none of them fails the job: the work has
    already landed or been closed, and refusing to finish tidying is not a
    reason to reopen a decision a human made.
    """
    repo = job.get("repo_settings") or settings.get("repo_settings") or {}
    workspace = str(job.get("workspace") or "")
    done = []

    if workspace and repo.get("cleanup"):
        result = run_command(worker, str(repo["cleanup"]), workspace,
                             dict(repo.get("env") or {}))
        done.append("cleanup" if result["ok"] else f"cleanup failed: {result.get('error')}")

    if job.get("worktree_id"):
        released = call(worker, "worktree::release",
                        {"worktree_id": job["worktree_id"], "session_id": job["id"]})
        done.append("released" if released["ok"] else "release failed")
        # Removed only when it landed or closed. A FAILED job keeps its
        # worktree on disk on purpose, because the first thing anybody wants
        # after a failure is to look at what the turn actually left behind.
        if str(job.get("stage")) in ("landed", "closed"):
            # `force` because a SQUASH merge leaves the branch commit outside
            # the target's ancestry, so git cannot see that it landed and
            # `remove` refuses with W221. The human merged it; the commits are
            # accounted for. Without this every squash-merged job leaks a
            # worktree, which is how three of them accumulated here.
            removed = call(worker, "worktree::remove",
                           {"worktree_id": job["worktree_id"], "force": True})
            done.append("removed" if removed["ok"] else "kept (still in use)")

    return {"ok": True, "did": done}


def say(worker, job: dict, body: str) -> dict:
    """Say something back on the request, if this forge has anywhere to say it.

    A driver with no channel returns no calls, and this reports `skipped`
    rather than `ok`. A forge that claims to have said something it did not is
    worse than one that admits the channel does not exist: the whole point of
    these messages is that a reviewer is not left watching a branch change with
    no explanation.
    """
    if not job.get("pr_number"):
        return {"ok": True, "skipped": "nothing open"}

    driver, problem = driver_for(job, {})
    if problem:
        return {"ok": True, "skipped": problem}

    calls = driver.say_calls(job, body)
    if not calls:
        return {"ok": True, "skipped": f"`{driver.name}` has no comment channel"}

    _, failed = perform(worker, calls)
    return failed or {"ok": True}


def announce_landing(worker, job: dict) -> dict:
    """Say on the request that ghola has finished with it."""
    return say(worker, job, publishing.landed_note(job))


def answer_pushed(worker, job: dict) -> dict:
    """Say on the request that the reworked answer is on the branch."""
    return say(worker, job, publishing.answer_note(job))


def acknowledge(worker, job: dict, brief: str) -> dict:
    """Reply under a reviewer's comment before reworking it.

    So the reviewer knows their comment was read, rather than watching a branch
    change under them with no explanation. The reply carries the marker, so the
    next poll does not read ghola's own acknowledgement as new feedback and
    rework forever.
    """
    return say(worker, job, publishing.reply_to(job, brief))


def stop(worker, job: dict, settings: dict) -> dict:
    return {"ok": True}


# ------------------------------------------------------- the pure decision

# ghola's own comments carry this, because it pushes with the operator's
# credentials and is therefore the pull request's author. Telling its own
# comments from a reviewer's by author would find none.
MARKER = "<!-- ghola -->"


def derive_outcome(job: dict, pr: dict) -> dict:
    """What the human did, as a pure function of the job and what the forge said.

    Pure and separate so every branch of the gate is testable without a pull
    request. This is the function wipp proved was worth extracting: its whole
    gate is one decision over two dicts.
    """
    state = str(pr.get("state") or "").lower()

    if pr.get("merged") or state == "merged":
        return {"outcome": "merge"}
    if state == "closed":
        return {"outcome": "close"}

    opened_at = pr.get("createdAt") or pr.get("created_at") or ""
    answered = str(job.get("answered_comment") or "")

    for comment in reversed(pr.get("comments") or []):
        body = str(comment.get("body") or "")
        when = str(comment.get("createdAt") or comment.get("created_at") or "")
        identity = str(comment.get("id") or when)

        if MARKER in body:
            continue                      # ghola's own
        if opened_at and when and when < opened_at:
            continue                      # older than the pull request
        if identity and identity == answered:
            continue                      # already turned into a rework
        return {"outcome": "comment", "brief": body, "comment_id": identity}

    return {"outcome": ""}


BUILT_IN = {
    "prepare_workspace": prepare_workspace,
    "commit_and_push": commit_and_push,
    "open_pull_request": open_pull_request,
    "watch_pull_request": watch_pull_request,
    "teardown": teardown,
    "stop": stop,
}
