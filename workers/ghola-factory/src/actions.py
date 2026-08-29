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
        made = call(worker, "worktree::create", {
            "repo_path": job.get("repo") or repo.get("path"),
            "session_id": job["id"],
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
    return {"ok": True, "pull_request": value.get("output") or value.get("url") or "",
            "number": value.get("number")}


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
    "open_pull_request": open_pull_request,
    "watch_pull_request": watch_pull_request,
    "teardown": teardown,
    "stop": stop,
}
