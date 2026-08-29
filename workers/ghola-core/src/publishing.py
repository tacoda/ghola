"""What a job publishes: the pull request body, and the replies under comments.

**Rung 4 sees this and no other rung does.** A commit message, a pull request
body and a reply are not written by any tool and are not part of any diff, so
nothing below the delivery gate has ever seen them. That is the whole reason
this module is separate and pure: the gate is handed exactly what is about to
be published, as a string, before it goes anywhere.

Everything here takes a job record and returns text.
"""

from __future__ import annotations

# How ghola tells its own comments from a reviewer's. **Not by author**: it
# pushes with the operator's credentials and IS the pull request's author, so
# an author check would find none of them.
MARKER = "<!-- ghola -->"

# What a reader should be able to answer from the body alone, in the order they
# will ask it: what is this, was it checked, and where did it come from.
MAX_SPEC = 4000
MAX_PLAN = 6000


def pull_request_body(job: dict, document: str = "") -> str:
    """The body of the pull request ghola opens.

    **This is the job document.** Each phase appended a section as it went, so
    by the time a human reads the pull request the account of the work is
    already written: what was asked, what was planned, what was built, what was
    proved, what review found. Nothing is summarised into existence here.

    An empty body — which is what the first real job shipped — makes a reviewer
    reconstruct all of that from the diff.
    """
    parts = [MARKER, ""]

    body = trim(str(document or "").strip(), MAX_SPEC + MAX_PLAN)
    if body:
        parts += [body, ""]
    else:
        # No document: fall back to the spec so the body is never empty.
        spec = str(job.get("spec") or "").strip()
        if spec:
            parts += ["## What was asked", "", trim(spec, MAX_SPEC), ""]

    checks = check_lines(job)
    if checks:
        parts += ["## What the checks said", ""] + checks + [""]

    parts += ["---", "", footer(job)]
    return "\n".join(parts).strip() + "\n"


def check_lines(job: dict) -> list[str]:
    """One line per check, saying plainly when a claim was downgraded.

    A downgrade is the most useful thing on the page: it means a check claimed
    something its own output did not support, and a human reading the pull
    request is the person who should know that.
    """
    lines = []

    proven = str(job.get("proven") or "")
    if proven:
        lines.append(f"- **prove**: `{proven}`" + downgrade_note(job, "proven"))

    verdict = str(job.get("verdict") or "")
    if verdict:
        lines.append(f"- **review**: `{verdict}`" + downgrade_note(job, "verdict"))
        for finding in (job.get("findings") or [])[:10]:
            lines.append(f"  - {finding}")

    revisions = int(job.get("revisions") or 0)
    if revisions:
        lines.append(f"- **revisions**: {revisions} "
                     "(the repository's own commit gate refused, and the refusal "
                     "was the brief for another attempt)")
    return lines


def downgrade_note(job: dict, which: str) -> str:
    if not job.get(f"{which}_downgraded"):
        return ""
    was = job.get(f"{which}_downgraded_from") or "?"
    return (f" — **downgraded from `{was}`**: the claim was not supported by its "
            "own output")


def footer(job: dict) -> str:
    """Where this came from, and what it is not.

    The last line is load-bearing: a reviewer should not have to wonder whether
    something merged this already.
    """
    return ("Opened by ghola from a spec. Nothing merges itself: this is a "
            "proposal, and a human decides.")


def reply_to(job: dict, brief: str) -> str:
    """What ghola says under a reviewer's comment before working on it.

    Posted so the reviewer knows their comment was read and by what, rather than
    watching a branch change under them with no explanation. It carries the
    marker so the next poll does not read it as new feedback and rework forever.
    """
    quoted = "\n".join(f"> {line}" for line in trim(brief, 600).splitlines())
    return (f"{MARKER}\n\nPicked this up:\n\n{quoted}\n\n"
            "Working on it now, on this same branch. The next push here is the "
            "answer.\n")


def landed_note(job: dict) -> str:
    """What ghola says when a job it opened has been merged."""
    return (f"{MARKER}\n\nMerged. The worktree has been torn down and the job is "
            "closed on ghola's side.\n")


def trim(text: str, limit: int) -> str:
    """Bounded, and it SAYS it was bounded.

    Silently truncating what a reviewer reads is the same failure as silently
    truncating what a check is given.
    """
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n\n*(truncated at {limit} characters)*"
