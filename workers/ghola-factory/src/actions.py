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

import governance
import jobs
import publishing


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

    base = str((settings.get("repo_settings") or {}).get("base") or "") or "HEAD"
    message = commit_message(job)

    # Stage whatever is loose, so the gate sees it whether the turn committed or
    # not. **The run phase can commit by itself**: it has `shell::exec` and
    # nothing withholds git from it, and the first rework run did exactly that.
    # A gate that only looked at staged changes would then see an empty diff and
    # wave through work it never read.
    run(worker, "git", ["add", "-A"], workspace)

    refused = rung_four(worker, job, workspace, message, base)
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
    ahead = run(worker, "git", ["log", "--oneline", f"origin/{base}..HEAD"], workspace)
    if ahead["ok"] and not str(ahead.get("output") or "").strip():
        return {"ok": False, "error": (
            "the turn finished and the branch has no commits on it, so there is "
            "nothing to publish")}

    pushed = run(worker, "git", ["push", "-u", "origin", branch], workspace)
    if not pushed["ok"]:
        return {"ok": False, "error": f"push failed: {pushed.get('error')}"}

    return {"ok": True, "committed": True, "branch": branch}


def title_for(job: dict) -> str:
    """The pull request's title.

    The spec's first line, with its markdown heading marker stripped: `# Do the
    thing` is a heading in a file and a stray `#` in a title.
    """
    first = str(job.get("title") or "").strip().lstrip("#").strip()
    return first[:70] or "ghola"


def commit_message(job: dict) -> str:
    """What the commit says.

    No AI attribution, and that is a rule rather than a preference: this
    repository's operator is the author, and a trailer naming a tool is
    something rung 4 refuses. It is not added here so it never has to be
    removed there.
    """
    title = str(job.get("title") or "").strip() or "ghola"
    return title.splitlines()[0][:72]


def rung_four(worker, job: dict, workspace: str, publishing: str,
              base: str = "HEAD") -> str:
    """The delivery gate, over the finished diff and the text about to ship.

    Asked of the `ladder` worker rather than reimplemented, so the same
    predicate that refuses a write at rung 3 refuses the finished file here.
    A ladder that is unreachable does not wave the commit through silently: it
    says so, and the caller records it.
    """
    # Everything not yet on the remote, committed or not. `--cached` alone
    # would miss work the turn committed itself, which is the hole that let a
    # diff reach a branch without the delivery gate reading it.
    diff = run(worker, "git", ["diff", f"origin/{base}...HEAD", "--unified=0"],
               workspace)
    changed = str(diff.get("output") or "") if diff["ok"] else ""
    staged = run(worker, "git", ["diff", "--cached", "--unified=0"], workspace)
    changed = (changed + "\n" + str(staged.get("output") or ""))[:200000]

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
    """Publish the work for a human to decide on. ghola never merges.

    **Idempotent.** A rework pushes to the same branch, so the pull request that
    already exists updates itself and there is nothing to open. The first rework
    ran the whole loop correctly and then tried to create a second pull request
    for a branch that already had one.
    """
    repo = settings.get("repo_settings") or {}
    slug = str(job.get("repo_slug") or "")

    if job.get("pr_number"):
        # Already open. Say on it that the answer has been pushed, so a reviewer
        # is not left watching a branch change with no explanation.
        answered = answer_pushed(worker, job)
        return {"ok": True, "pull_request": job.get("pull_request"),
                "pr_number": job["pr_number"],
                "reopened": False, "commented": answered["ok"]}
    if not slug:
        return {"ok": False, "error": (
            "no `owner/name` for this repository, so there is nothing to open a "
            "pull request against. Set `repo_slug` on the job or `slug` in "
            "repos.toml")}

    made = call(worker, "github::pr::create", {
        "repo": slug,
        "title": title_for(job),
        # The first real job opened a pull request with an EMPTY body, which
        # makes a reviewer reconstruct what was asked and what was checked from
        # the diff alone.
        # The document the phases built, which is the account of the work.
        "body": publishing.pull_request_body(job, job.get("document") or ""),
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

    pr = dict(seen["value"].get("value") or seen["value"])
    pr["comments"] = comments_on(worker, slug, number)
    return {"ok": True, **derive_outcome(job, pr)}


def comments_on(worker, slug: str, number: int) -> list[dict]:
    """Every comment on a pull request, from the endpoints `pr::view` omits.

    **`github::pr::view` returns no comments.** It carries the body,
    mergeability, review decision and diff stats, and a reconciler reading it
    alone sees a card nobody has ever commented on — which is exactly what a
    card nobody has commented on looks like. The first rework test waited three
    minutes on a comment that was already there.

    Two endpoints, because GitHub keeps them apart: issue comments are the
    conversation, and pull comments are the ones anchored to a line. A reviewer
    does not distinguish them and neither does this.
    """
    found = []
    for path in (f"repos/{slug}/issues/{number}/comments",
                 f"repos/{slug}/pulls/{number}/comments"):
        answer = call(worker, "github::api", {"path": path, "method": "GET"})
        if not answer["ok"]:
            continue
        value = answer["value"]
        items = value.get("value") or value.get("data") or value
        if isinstance(items, str):
            try:
                import json as _json
                items = _json.loads(items)
            except ValueError:
                continue
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    # A line comment carries its file and line; keeping them
                    # means the brief can say WHERE, which is most of what makes
                    # a review comment actionable.
                    where = (f"{item.get('path')}:{item.get('line')} — "
                             if item.get("path") else "")
                    found.append({
                        "id": str(item.get("id") or ""),
                        "body": where + str(item.get("body") or ""),
                        "createdAt": str(item.get("created_at")
                                         or item.get("createdAt") or ""),
                    })

    return sorted(found, key=lambda c: c["createdAt"])


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


def announce_landing(worker, job: dict) -> dict:
    """Say on the pull request that ghola has finished with it."""
    if not job.get("repo_slug") or not job.get("pr_number"):
        return {"ok": True}
    return call(worker, "github::pr::comment", {
        "repo": job["repo_slug"], "number": job["pr_number"],
        "body": publishing.landed_note(job)})


def answer_pushed(worker, job: dict) -> dict:
    """Say on the pull request that the reworked answer is on the branch."""
    if not job.get("repo_slug") or not job.get("pr_number"):
        return {"ok": True}
    return call(worker, "github::pr::comment", {
        "repo": job["repo_slug"], "number": job["pr_number"],
        "body": publishing.answer_note(job)})


def acknowledge(worker, job: dict, brief: str) -> dict:
    """Reply under a reviewer's comment before reworking it.

    So the reviewer knows their comment was read, rather than watching a branch
    change under them with no explanation. The reply carries the marker, so the
    next poll does not read ghola's own acknowledgement as new feedback and
    rework forever.
    """
    if not job.get("repo_slug") or not job.get("pr_number"):
        return {"ok": True}
    return call(worker, "github::pr::comment", {
        "repo": job["repo_slug"], "number": job["pr_number"],
        "body": publishing.reply_to(job, brief)})


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
