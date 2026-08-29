"""The job document: a spec that builds as it goes.

**The interface between phases is a file.** Not a string on a job record, not a
field the next phase hopes was set. A job starts as a copy of its spec and each
phase appends what it produced, so by the time it reaches a human the document
*is* the account of the work: what was asked, what was planned, what was built,
what was proved, what was found.

That makes entry and exit criteria expressible, which is the point:

    plan:
      requires: [spec]     # it cannot start without one
      produces: [plan]     # it is not done until it wrote one

A phase whose entry criteria are unmet is a phase that would run on nothing. A
phase that finishes without its exit criteria is a phase that returned something
nobody can use — and both are silent today, which is why they are checked here.

**The authored spec is never rewritten.** It is the input of record and it lives
in `specs/`. This document is a working copy, and the difference matters when an
interrupt amends the contract: the answer to a question changes what the checks
are graded against without editing what a person wrote.

Everything here is pure text in and text out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The sections a phase can require or produce. A name not in here is a typo
# rather than a new idea, and `make pipeline` says so before a job runs.
SECTIONS = {
    # The rough version somebody typed. Kept beside the spec rather than
    # replaced by it, so a reviewer can see what was asked for AND what it was
    # refined into — which is the only way to notice a refinement that drifted.
    "idea": "The idea, as it arrived",
    "spec": "What was asked",
    "plan": "The plan",
    "answer": "The question, and its answer",
    "work": "What was built",
    "proof": "What was proved",
    "review": "What review found",
    "refusal": "What the gate refused",
}

HEADING = "## "
# `<!-- ghola:plan -->` under each heading. The marker rather than the heading
# text is what identifies a section, so a phase may retitle its own output
# without the next phase losing it.
MARKER = re.compile(r"<!--\s*ghola:([a-z-]+)\s*-->")


@dataclass
class Document:
    """One job's accumulating account of itself."""

    text: str = ""

    # ------------------------------------------------------------ reading

    def sections(self) -> dict[str, str]:
        """Every section present, by name.

        Split on the markers rather than on headings, so prose containing `##`
        does not invent a section.
        """
        found: dict[str, str] = {}
        marks = list(MARKER.finditer(self.text))
        for index, mark in enumerate(marks):
            if index + 1 < len(marks):
                # Stop at the NEXT section's heading, not at its marker. The
                # heading line sits above the marker, so slicing to the marker
                # swallows it and every section ends with the next one's title.
                nxt = marks[index + 1].start()
                heading = self.text.rfind("\n" + HEADING, mark.end(), nxt)
                end = heading if heading != -1 else nxt
            else:
                end = len(self.text)
            found[mark.group(1)] = self.text[mark.end():end].strip()
        return found

    def has(self, name: str) -> bool:
        """Whether a section exists AND says something.

        An empty section is not a section. A phase that produced a heading and
        no content has not met its exit criteria, and counting it would make the
        check worthless.
        """
        return bool(self.sections().get(name, "").strip())

    def get(self, name: str) -> str:
        return self.sections().get(name, "")

    def missing(self, required: tuple[str, ...]) -> list[str]:
        return [name for name in required if not self.has(name)]

    # ------------------------------------------------------------ writing

    def add(self, name: str, body: str, title: str = "") -> "Document":
        """Append a section, or replace it if it is already there.

        Replaced rather than duplicated because a revision runs the same phase
        again: two `## What was built` sections would leave a reviewer deciding
        which one is current, which is a question the document should never ask.
        """
        body = str(body or "").strip()
        heading = title or SECTIONS.get(name, name.replace("-", " ").title())
        block = f"{HEADING}{heading}\n<!-- ghola:{name} -->\n\n{body}\n"

        if name in self.sections():
            return Document(self._replace(name, block))
        joined = self.text.rstrip()
        return Document((joined + "\n\n" + block) if joined else block)

    def _replace(self, name: str, block: str) -> str:
        marks = list(MARKER.finditer(self.text))
        for index, mark in enumerate(marks):
            if mark.group(1) != name:
                continue
            # Back up over the heading line the marker sits under.
            start = self.text.rfind(HEADING, 0, mark.start())
            start = start if start != -1 else mark.start()
            end = marks[index + 1].start() if index + 1 < len(marks) else len(self.text)
            end = self.text.rfind(HEADING, 0, end) if index + 1 < len(marks) else end
            return (self.text[:start].rstrip() + "\n\n" + block
                    + "\n" + self.text[end:].lstrip()).rstrip() + "\n"
        return self.text


def start(spec: str, title: str = "") -> Document:
    """A new document, from the authored spec.

    The spec is copied in as the first section rather than referenced, so the
    document is readable on its own: a reviewer opening it should not have to
    find another file to learn what was asked.
    """
    heading = f"# {title.lstrip('#').strip()}\n\n" if title else ""
    return Document(heading).add("spec", spec)


def read(text: str) -> Document:
    return Document(str(text or ""))


# ------------------------------------------------------- entry and exit

@dataclass
class Check:
    """Whether a phase may start, or is finished."""

    ok: bool
    missing: tuple[str, ...] = ()
    why: str = ""


def may_start(doc: Document, requires: tuple[str, ...]) -> Check:
    """Entry criteria: what must already be in the document.

    A phase whose entry criteria are unmet would run on nothing and produce
    something confident about it, which costs a turn and reads like an answer.
    """
    absent = doc.missing(requires)
    if not absent:
        return Check(True)
    return Check(False, tuple(absent), (
        f"needs {', '.join(absent)} in the document and there "
        f"{'is' if len(absent) == 1 else 'are'} none. An earlier phase either "
        "did not run or produced nothing"))


def is_finished(doc: Document, produces: tuple[str, ...]) -> Check:
    """Exit criteria: what this phase had to add.

    A phase that finishes without producing what it promised has returned
    something nobody downstream can use. Silent today; named here.
    """
    absent = doc.missing(produces)
    if not absent:
        return Check(True)
    return Check(False, tuple(absent), (
        f"was supposed to produce {', '.join(absent)} and the document has "
        "none. The turn finished without doing what the stage is for"))


def unknown_sections(names: tuple[str, ...]) -> list[str]:
    """Names no phase can satisfy, so `make pipeline` catches a typo before a run."""
    return [n for n in names if n not in SECTIONS]
