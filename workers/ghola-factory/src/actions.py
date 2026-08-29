"""The built-in stage actions: what a stage does when it is not running a turn.

Every one of these is a thin call to a stock worker. ghola runs no git and talks
to no forge directly, which is the whole reason this file is short:

| action | what it actually calls |
|---|---|
| `prepare_workspace` | `worktree::create` and `worktree::claim`, then `shell::exec` |
| `open_pull_request` | `github::pr::create` |
| `watch_pull_request` | `github::pr::view` and `github::api` |
| `teardown` | `shell::exec`, then `worktree::release` |

An action returns the same shape a turn does — `{ok, refused, blocked, outcome,
error}` — so `graph.next_stage` does not care which kind of stage it just ran.
That symmetry is what keeps the state machine a pure function of two dicts.
"""

from __future__ import annotations

import shlex

import governance
import jobs


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


def run_command(worker, command: str, cwd: str, env: dict | None = None,
                timeout_ms: int = 600000) -> dict:
    """A repository's own command, through the `shell` worker.

    Used for `prepare` and `cleanup`. An empty command is a success rather than
    a no-op error: most repositories need neither.
    """
    if not command.strip():
        return {"ok": True, "value": {"skipped": "no command configured"}}
    return call(worker, "shell::exec",
                {"command": command, "cwd": cwd, "env": env or {}},
                timeout_ms=timeout_ms)


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

    status = call(worker, "worktree::status", {"worktree_id": job.get("worktree_id")})
    if status["ok"]:
        state = status["value"].get("value") or status["value"]
        if state.get("clean", False) and not state.get("ahead"):
            # A run that changed nothing is not a failure, but it is not a pull
            # request either. Saying so beats opening an empty one.
            return {"ok": False, "error": (
                "the turn finished and the worktree is unchanged, so there is "
                "nothing to publish")}

    message = commit_message(job)

    refused = rung_four(worker, job, workspace, message)
    if refused:
        return {"ok": True, "refused": True, "refusal": refused}

    committed = call(worker, "shell::exec", {
        "command": f"git add -A && git commit -m {shlex.quote(message)}",
        "cwd": workspace}, timeout_ms=300000)
    if not committed["ok"]:
        # The repository's own hook refused. Verbatim, because summarising it
        # would throw away the only specific thing anybody said.
        return {"ok": True, "refused": True,
                "refusal": str(committed.get("error") or "")[:4000]}

    pushed = call(worker, "shell::exec", {
        "command": f"git push -u origin {shlex.quote(branch)}",
        "cwd": workspace}, timeout_ms=300000)
    if not pushed["ok"]:
        return {"ok": False, "error": f"push failed: {pushed.get('error')}"}

    return {"ok": True, "committed": True, "branch": branch}


def commit_message(job: dict) -> str:
    """What the commit says.

    No AI attribution, and that is a rule rather than a preference: this
    repository's operator is the author, and a trailer naming a tool is
    something rung 4 refuses. It is not added here so it never has to be
    removed there.
    """
    title = str(job.get("title") or "").strip() or "ghola"
    return title.splitlines()[0][:72]


def rung_four(worker, job: dict, workspace: str, publishing: str) -> str:
    """The delivery gate, over the finished diff and the text about to ship.

    Asked of the `ladder` worker rather than reimplemented, so the same
    predicate that refuses a write at rung 3 refuses the finished file here.
    A ladder that is unreachable does not wave the commit through silently: it
    says so, and the caller records it.
    """
    diff = call(worker, "shell::exec",
                {"command": "git add -A && git diff --cached --unified=0",
                 "cwd": workspace}, timeout_ms=120000)
    changed = ""
    if diff["ok"]:
        changed = str((diff["value"].get("stdout") or ""))[:200000]

    answer = call(worker, "ladder::evaluate", {
        "repo": workspace,
        "path": "",
        "content": changed,
        "publishing": publishing,
        "rung": 4,
    }, timeout_ms=60000)

    if not answer["ok"]:
        return ""
    body = answer["value"]
    return "" if body.get("allowed", True) else str(body.get("reason") or "refused")


def open_pull_request(worker, job: dict, settings: dict) -> dict:
    """Publish the work for a human to decide on. ghola never merges."""
    repo = settings.get("repo_settings") or {}
    slug = str(job.get("repo_slug") or "")
    if not slug:
        return {"ok": False, "error": (
            "no `owner/name` for this repository, so there is nothing to open a "
            "pull request against. Set `repo_slug` on the job or `slug` in "
            "repos.toml")}

    made = call(worker, "github::pr::create", {
        "repo": slug,
        "title": job.get("title") or job.get("spec") or "ghola",
        "body": job.get("pr_body") or "",
        "head": job.get("branch") or "",
        **({"base": repo["base"]} if repo.get("base") else {}),
    })
    if not made["ok"]:
        return made

    value = made["value"]
    url = str(value.get("output") or value.get("url") or "").strip()
    # `gh pr create` prints the URL and the number is the last path segment.
    # Without this the record has no `pr_number` and `watch_pull_request`
    # answers "no pull request to watch" forever, which looks exactly like a
    # card nobody has acted on.
    number = value.get("number")
    if not number and url:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        number = int(tail) if tail.isdigit() else None

    return {"ok": True, "pull_request": url, "pr_number": number}


def watch_pull_request(worker, job: dict, settings: dict) -> dict:
    """Read the pull request and report what the human did.

    Returns an `outcome` the graph turns into an edge: merge lands it, close
    closes it, a comment is a brief for another turn. **Nothing is a legitimate
    answer** and means the card waits.

    ghola tells its own comments from a reviewer's by a marker rather than by
    author, because it pushes with the operator's credentials and *is* the pull
    request's author.
    """
    slug, number = str(job.get("repo_slug") or ""), job.get("pr_number")
    if not slug or not number:
        return {"ok": False, "error": "no pull request to watch"}

    seen = call(worker, "github::pr::view", {"repo": slug, "number": number})
    if not seen["ok"]:
        return seen

    pr = seen["value"].get("value") or seen["value"]
    return {"ok": True, **derive_outcome(job, pr)}


def teardown(worker, job: dict, settings: dict) -> dict:
    """Run the repository's cleanup, then give the worktree back."""
    repo = settings.get("repo_settings") or {}
    workspace = str(job.get("workspace") or "")

    if workspace:
        run_command(worker, str(repo.get("cleanup") or ""), workspace,
                    dict(repo.get("env") or {}))
    if job.get("worktree_id"):
        call(worker, "worktree::release",
             {"worktree_id": job["worktree_id"], "session_id": job["id"]})
    return {"ok": True}


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
