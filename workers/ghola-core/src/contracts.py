"""What a phase's answer has to look like, and what invalidates it.

A check that grades itself is not a check. `prove` claims the software works and
`review` claims the diff is sound, and both claims are worth exactly what the
evidence under them is worth. A contract is how that gets enforced without
asking a model to be honest about its own output.

Two rules do most of the work, and they are the same rule twice:

- **`PROVEN: yes` with no command under any criterion is downgraded to
  `unproven`.** Evidence or it did not happen.
- **An objecting review with no findings is downgraded.** A verdict of
  `concerns` that names nothing is a mood.

And one that matters more than either: **an answer that cannot be parsed is
never read as a pass.** It becomes `unreadable`, which a person looks at. The
failure this prevents is a check whose output format drifted, silently reading
as approval for weeks.

Everything here is pure. A contract is a dict and an answer is a string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The built-ins, in the shape `settings/contracts/<name>.yaml` uses. A team
# overrides a file; the defaults are what they are overriding.
BUILT_IN = {
    "proven": {
        "marker": "PROVEN:",
        "values": ["yes", "no", "partial"],
        # Never a pass. `unproven` is the honest state for an answer nobody
        # could read, and it is not the same as `no`.
        "unparseable": "unproven",
        "patterns": {
            # A line that ran something. This is what "evidence" means here, and
            # it is deliberately syntactic: a model claiming it ran a command is
            # not the same as a transcript containing one.
            "evidence": r"^\s*[$>]\s+\S",
        },
        "requires": [
            {"when": ["yes"], "at_least_one": "evidence", "otherwise": "unproven",
             "why": "a proof with no command under it is a claim, not a proof"},
        ],
    },
    "verdict": {
        "marker": "VERDICT:",
        "values": ["pass", "concerns", "blocker"],
        "unparseable": "unreadable",
        "patterns": {
            # A finding names a place. `app.py:9 — …` and `- src/x.rb:22:` both
            # count; a paragraph of prose does not.
            "finding": r"^\s*[-*]?\s*\S+\.\w+:\d+",
        },
        "requires": [
            {"when": ["concerns", "blocker"], "at_least_one": "finding",
             "otherwise": "unreadable",
             "why": "an objecting review that names nothing is a mood"},
        ],
    },
}


@dataclass
class Answer:
    """What a phase actually said, after the contract has had its say."""

    value: str = ""
    raw: str = ""
    findings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    downgraded_from: str = ""
    why: str = ""
    text: str = ""

    @property
    def downgraded(self) -> bool:
        return bool(self.downgraded_from)

    @property
    def objects(self) -> bool:
        """Whether this answer is a complaint the pipeline should act on."""
        return self.value in ("concerns", "blocker", "no", "unproven", "unreadable")


def contract(name: str, config: dict | None = None) -> dict:
    """One contract: the file merged over the built-in, or the built-in."""
    built_in = BUILT_IN.get(name)
    if built_in is None and not config:
        return {}
    merged = dict(built_in or {})
    merged.update(config or {})
    return merged


def matches(pattern: str, text: str) -> tuple[str, ...]:
    if not pattern:
        return ()
    found = re.compile(pattern, re.MULTILINE)
    return tuple(line.strip() for line in text.splitlines() if found.match(line))


def read(text: str, spec: dict) -> Answer:
    """Parse an answer against a contract, applying every downgrade.

    The marker is looked for at the start of a line, so a phase that *mentions*
    `VERDICT:` mid-sentence while explaining itself does not accidentally
    declare one.
    """
    text = str(text or "")
    marker = str(spec.get("marker") or "")
    values = [str(v).lower() for v in (spec.get("values") or [])]
    unparseable = str(spec.get("unparseable") or "unreadable")
    patterns = spec.get("patterns") or {}

    answer = Answer(raw=text, text=text)
    answer.findings = matches(str(patterns.get("finding") or ""), text)
    answer.evidence = matches(str(patterns.get("evidence") or ""), text)

    declared = ""
    if marker:
        found = re.search(rf"^\s*{re.escape(marker)}\s*(\S+)", text, re.MULTILINE)
        if found:
            declared = found.group(1).strip().strip(".,;*_`").lower()

    if not declared:
        answer.value = unparseable
        answer.why = (f"no `{marker}` line, so there is nothing to read. This is "
                      "not a pass: an answer nobody can parse is an answer nobody "
                      "checked")
        return answer

    if values and declared not in values:
        answer.value = unparseable
        answer.downgraded_from = declared
        answer.why = (f"`{declared}` is not one of {', '.join(values)}. An "
                      "unrecognised verdict is never read as a pass")
        return answer

    answer.value = declared

    # The downgrades. Each is a claim the answer made that its own body does not
    # support.
    for rule in spec.get("requires") or []:
        when = [str(v).lower() for v in (rule.get("when") or [])]
        if when and answer.value not in when:
            continue

        needed = str(rule.get("at_least_one") or "")
        have = answer.findings if needed == "finding" else answer.evidence
        if needed and not have:
            answer.downgraded_from = answer.value
            answer.value = str(rule.get("otherwise") or unparseable)
            answer.why = str(rule.get("why") or
                             f"claimed `{answer.downgraded_from}` with no {needed}")
            return answer

    return answer


def as_result(answer: Answer, stage: str = "") -> dict:
    """What the pipeline does with a parsed answer.

    A contract does **not** fail a job on its own. `review` never blocks: pass,
    concerns and blocker all land as a comment and the human decides. In a dark
    factory a check reports; only the merge accepts.

    `prove` is the same shape. What a downgrade changes is what gets published,
    not whether the work proceeds.
    """
    return {
        "ok": True,
        "verdict": answer.value,
        "downgraded": answer.downgraded,
        "downgraded_from": answer.downgraded_from,
        "why": answer.why,
        "findings": list(answer.findings),
        "evidence": list(answer.evidence),
    }


# ------------------------------------------------------------- interrupts

INTERRUPT = "INTERRUPT:"


def interrupt(text: str) -> str:
    """The question a turn stopped to ask, or an empty string.

    **Only an opening line counts.** A summary that mentions the word is not a
    question, and checking anywhere in the text is how a turn that wrote "no
    INTERRUPT: needed" blocks a job.

    The hatch is deliberately narrow: contradictory requirements, a missing
    credential, a choice that would destroy data. Not preferences, not naming,
    not anything the codebase already answers.
    """
    first = (str(text or "").strip().splitlines() or [""])[0].strip()
    return first[len(INTERRUPT):].strip() if first.startswith(INTERRUPT) else ""
