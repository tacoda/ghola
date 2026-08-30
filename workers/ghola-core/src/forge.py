"""Where a request for review goes, and how ghola hears back.

The factory's shape does not depend on GitHub, but until this module existed its
code did: `github::pr::create` was written into the publish action, and a team on
GitLab or on no forge at all had a fork rather than a setting.

A driver answers four questions and nothing else — how to open a request, how to
read its state, how to read what people said on it, and how to say something
back. Everything here is **pure**: a driver returns the calls to make and reads
the answers that come back, and the factory does the calling. That is what lets
a forge be tested without one.

Two ship. `github` is the stock worker. `local` is no forge at all: the request
is a markdown file in the repository and a merge is a merge, which makes ghola
runnable against a repository that has no forge account behind it — and is the
proof that the seam is a seam rather than a rename.

A third is `forges/<name>.py` defining `driver`, found by filename like every
other extension here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

# ghola's own comments carry this, because it pushes with the operator's
# credentials and is therefore the request's author. Telling its own comments
# from a reviewer's by author would find none.
MARKER = "<!-- ghola -->"


def title_of(job: dict) -> str:
    """What the request is called.

    The spec's first line with its markdown heading marker stripped: `# Do the
    thing` is a heading in a file and a stray `#` in a title.
    """
    first = str(job.get("title") or "").strip().lstrip("#").strip()
    return first[:70] or "ghola"


def call(function_id: str, payload: dict, allow_failure: bool = False) -> dict:
    """One call for the factory to make on the driver's behalf."""
    return {"function_id": function_id, "payload": payload,
            "allow_failure": allow_failure}


@dataclass(frozen=True)
class Driver:
    """One forge, as four pairs of pure functions.

    Each `*_calls` returns what to invoke; each reader turns the answers back
    into the shape the rest of the factory already understands. `state` in
    particular must produce what `derive_outcome` reads — `state`, `merged`,
    `createdAt` and `comments` — because that gate is the one decision this
    seam exists to keep forge-agnostic.
    """

    name: str
    # "" when the job carries what this driver needs, otherwise the reason.
    ready: Callable[[dict], str]
    open_calls: Callable[[dict, str], list]
    opened: Callable[[dict, list], dict]
    view_calls: Callable[[dict], list]
    state: Callable[[dict, list], dict]
    comment_calls: Callable[[dict], list]
    comments: Callable[[list], list]
    say_calls: Callable[[dict, str], list]
    # What this driver calls the thing, for anything a person reads.
    noun: str = "pull request"
    # Where the branch has to be before anybody can look at it. Empty means
    # nowhere: a repository with no forge has no remote, and the branch is
    # already in the checkout the reviewer will open.
    # ponytail: one remote per forge. A repo pushing to two would need a list.
    remote: str = "origin"


def value_of(answer: dict) -> dict:
    """The payload out of one `{ok, value}`, whatever it wrapped it in."""
    if not isinstance(answer, dict):
        return {}
    value = answer.get("value")
    if isinstance(value, dict):
        return dict(value.get("value") or value)
    return {}


def text_of(answer: dict) -> str:
    value = value_of(answer)
    for key in ("content", "text", "output", "stdout"):
        found = value.get(key)
        if isinstance(found, str):
            return found
        if isinstance(found, list) and found and isinstance(found[0], dict):
            return str(found[0].get("content") or found[0].get("text") or "")
    return ""


def as_list(answer: dict) -> list:
    """A forge endpoint's array, whether it arrived parsed or as JSON text."""
    value = answer.get("value") if isinstance(answer, dict) else None
    if isinstance(value, dict):
        value = value.get("value") or value.get("data") or value.get("output") or value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


# ------------------------------------------------------------------- github

def github_ready(job: dict) -> str:
    if not job.get("repo_slug"):
        return ("no `owner/name` for this repository, so there is nothing to "
                "open a pull request against. Set `repo_slug` on the job or "
                "`slug` in repos.toml")
    return ""


def github_open(job: dict, body: str) -> list:
    repo = job.get("repo_settings") or {}
    return [call("github::pr::create", {
        "repo": job.get("repo_slug"),
        "title": title_of(job),
        "body": body,
        "head": job.get("branch") or "",
        **({"base": repo["base"]} if repo.get("base") else {}),
    })]


def github_opened(job: dict, answers: list) -> dict:
    value = value_of(answers[0]) if answers else {}
    url = str(value.get("output") or value.get("url") or "").strip()

    # `gh pr create` prints the URL and the number is the last path segment.
    # Without this the record has no `pr_number` and the reconciler answers "no
    # pull request to watch" forever, which looks exactly like a card nobody has
    # acted on.
    number = value.get("number")
    if not number and url:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        number = int(tail) if tail.isdigit() else None
    return {"pull_request": url, "pr_number": number}


def github_view(job: dict) -> list:
    return [call("github::pr::view", {"repo": job.get("repo_slug"),
                                      "number": job.get("pr_number")})]


def github_state(job: dict, answers: list) -> dict:
    """What the forge said, with the keys the gate reads guaranteed present.

    Defaults first, so a read that came back empty is an open request rather
    than an absent `merged` the gate has to interpret. A failed view must never
    be able to look like a landing.
    """
    return {"state": "open", "merged": False, "createdAt": "",
            **(value_of(answers[0]) if answers else {})}


def github_comment_calls(job: dict) -> list:
    """Two endpoints, because GitHub keeps them apart.

    **`github::pr::view` returns no comments.** It carries the body,
    mergeability, review decision and diff stats, and a reconciler reading it
    alone sees a request nobody has ever commented on — which is exactly what a
    request nobody has commented on looks like. The first rework test waited
    three minutes on a comment that was already there.

    Issue comments are the conversation and pull comments are anchored to a
    line. A reviewer does not distinguish them and neither does this.
    """
    slug, number = job.get("repo_slug"), job.get("pr_number")
    return [call("github::api", {"path": path, "method": "GET"}, allow_failure=True)
            for path in (f"repos/{slug}/issues/{number}/comments",
                         f"repos/{slug}/pulls/{number}/comments")]


def github_comments(answers: list) -> list:
    found = []
    for answer in answers:
        for item in as_list(answer):
            if not isinstance(item, dict):
                continue
            # A line comment carries its file and line. Keeping them means the
            # brief can say WHERE, which is most of what makes a review comment
            # actionable.
            where = f"{item.get('path')}:{item.get('line')} — " if item.get("path") else ""
            found.append({
                "id": str(item.get("id") or ""),
                "body": where + str(item.get("body") or ""),
                "createdAt": str(item.get("created_at") or item.get("createdAt") or ""),
            })
    return sorted(found, key=lambda c: c["createdAt"])


def github_say(job: dict, body: str) -> list:
    return [call("github::pr::comment", {"repo": job.get("repo_slug"),
                                         "number": job.get("pr_number"),
                                         "body": body})]


GITHUB = Driver(
    name="github", ready=github_ready,
    open_calls=github_open, opened=github_opened,
    view_calls=github_view, state=github_state,
    comment_calls=github_comment_calls, comments=github_comments,
    say_calls=github_say)


# -------------------------------------------------------------------- local

# The request, as a file in the repository being worked on. Written to the main
# checkout rather than the worktree, because the worktree is released when the
# job ends and the record of what was asked should outlive it.
REQUESTS = ".ghola/requests"
STATUS = re.compile(r"^\s*[-*]\s*status\s*:\s*(\w+)", re.MULTILINE | re.IGNORECASE)
# Where the conversation starts, as a marker rather than as the heading above
# it. The heading is prose, and prose gets quoted: ghola's own instruction line
# said "write under `## comments`", the split matched THAT occurrence, and the
# entire request — spec, plan, proof, review — came back as one reviewer comment.
# The job reworked itself against its own document.
CONVERSATION = "<!-- ghola:comments -->"
HEADING = "## comments"
SEPARATOR = re.compile(r"^---+\s*$", re.MULTILINE)
# Every html comment except ghola's own marker, which has to survive.
NOISE = re.compile(r"<!--(?!\s*ghola\s*-->).*?-->", re.DOTALL)


def request_path(job: dict) -> str:
    branch = str(job.get("branch") or job.get("id") or "request")
    return f"{REQUESTS}/{branch.replace('/', '-')}.md"


def local_ready(job: dict) -> str:
    if not job.get("repo"):
        return "no repository path, so there is nowhere to write the request"
    if not job.get("branch"):
        return "no branch, so there is nothing to ask anybody to review"
    return ""


def local_open(job: dict, body: str) -> list:
    repo = job.get("repo_settings") or {}
    base = str(repo.get("base") or "main")
    document = f"""# {title_of(job)}

- status: open
- branch: `{job.get('branch')}`
- base: `{base}`

To land this, merge the branch. To reject it, set the status above to `closed`.
To ask for a change, write at the bottom of this file under the comments
heading, separating each comment with a line of three dashes.

{body}

{HEADING}

{CONVERSATION}
<!-- Write below this line. `---` on its own line starts another comment. -->
"""
    return [call("coder::create-file", {
        "files": [{"path": f"{job.get('repo')}/{request_path(job)}",
                   "content": document, "overwrite": True, "parents": True}]})]


def local_opened(job: dict, answers: list) -> dict:
    path = f"{job.get('repo')}/{request_path(job)}"
    # The path IS the identity here. `pr_number` is only ever compared against
    # nothing and handed back to the driver, so a string is as good as an int
    # and a great deal more useful to read.
    return {"pull_request": path, "pr_number": request_path(job)}


def local_view(job: dict) -> list:
    repo = job.get("repo_settings") or {}
    base = str(repo.get("base") or "main")
    return [
        call("coder::read-file", {"path": f"{job.get('repo')}/{request_path(job)}"},
             allow_failure=True),
        # Exit 0 when the branch is an ancestor of the base, which is what
        # "somebody merged this" looks like without a forge to ask.
        call("shell::exec", {"command": "git",
                             "args": ["merge-base", "--is-ancestor",
                                      str(job.get("branch") or ""), base],
                             "cwd": str(job.get("repo") or "")},
             allow_failure=True),
    ]


def local_state(job: dict, answers: list) -> dict:
    document = text_of(answers[0]) if answers else ""
    merged = value_of(answers[1]) if len(answers) > 1 else {}

    status = STATUS.search(document)
    state = (status.group(1).lower() if status else "open")

    return {
        "state": state,
        # A squash merge leaves no ancestry, so this reports what git can see
        # and the human closing the file is the fallback. Said plainly in the
        # request itself rather than left as a surprise.
        "merged": int(merged.get("exit_code", 1)) == 0,
        "createdAt": "",
        "body": document,
    }


def local_comment_calls(job: dict) -> list:
    # The same file. Reading it twice would be two reads of one thing, so the
    # factory hands the state answers straight back.
    return []


def local_comments(answers: list) -> list:
    """Whatever a person wrote under the conversation heading.

    No timestamps, because a file has none per comment. The id is a hash of the
    text, which is what makes "already turned into a rework" answerable: the
    same words are the same comment, and editing them is a new one.
    """
    document = text_of(answers[0]) if answers else ""
    _, marker, tail = document.partition(CONVERSATION)
    if not marker:
        return []

    found = []
    for chunk in SEPARATOR.split(tail):
        # The instruction line ghola wrote into the file is not a comment, so
        # html comments come out — **except its own marker**, which is the only
        # thing telling ghola's notes from a reviewer's. Stripping that too
        # would make every note it left read back as somebody asking for a
        # change, and rework the job against its own voice.
        body = NOISE.sub("", chunk).strip()
        if not body:
            continue
        found.append({"id": hashlib.sha256(body.encode()).hexdigest()[:12],
                      "body": body, "createdAt": ""})
    return found


def local_say(job: dict, body: str) -> list:
    """Appending to the file would need its current contents, so this says
    nothing rather than pretending to.

    A local request has no notifications for a comment to reach anybody through,
    and the branch is right there. Reported as skipped rather than as sent,
    because a driver that claims to have said something it did not is worse than
    one that admits the channel does not exist.
    """
    return []


LOCAL = Driver(
    name="local", ready=local_ready,
    open_calls=local_open, opened=local_opened,
    view_calls=local_view, state=local_state,
    comment_calls=local_comment_calls, comments=local_comments,
    say_calls=local_say, noun="request", remote="")


BUILT_IN = {"github": GITHUB, "local": LOCAL}


def named(name: str) -> Driver | None:
    return BUILT_IN.get((name or "").strip().lower())


def for_job(job: dict, default: str = "github") -> str:
    """Which driver this job uses.

    The job's own setting first, because it was copied off `repos.toml` when the
    job was created: a repository that moved forge last month should not change
    how a rework of an old job is delivered.
    """
    settings = job.get("repo_settings") or {}
    return str(job.get("forge") or settings.get("forge") or default or "github")
