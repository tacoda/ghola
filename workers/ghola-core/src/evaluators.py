"""What ghola contributes to the `eval` worker: the judgements it cannot make.

**ghola does not write an eval runner.** The `eval` worker already runs durable
same-model A/B evaluations, alternates variant order to reduce order bias,
persists reports and injects a console page. What it leaves open — deliberately
— is the one thing it cannot know: whether a particular answer was any good.

An evaluator receives `(output, metrics, arguments, role)` and returns
`{passed, score?, reason?, details?}`. It must be **deterministic and
idempotent**, because durable delivery is at-least-once and an evaluator that
answered differently on a redelivery would make the report a coin toss.

Everything here is pure. The worker registration is fifteen lines elsewhere.

**These are the same checks the pipeline already runs**, reached through the
eval worker instead of a stage: `contracts.read` is what `prove` and `review`
are graded by in production, so an eval measures the thing that actually ships
rather than a second implementation of it that can drift.
"""

from __future__ import annotations

import re

import contracts


def text_of(output) -> str:
    """The model's words, whatever shape the runner hands them in.

    An evaluator that only understood one shape would report `passed: false` for
    a turn that answered correctly, which is worse than not running: it looks
    like evidence.
    """
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("text", "result", "content", "message"):
            value = output.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                return text_of(value)
            if isinstance(value, list):
                return "\n".join(
                    str(b.get("text") or "") for b in value
                    if isinstance(b, dict) and b.get("type") in (None, "text"))
    if isinstance(output, list):
        return "\n".join(text_of(item) for item in output)
    return str(output or "")


class UnknownContract(LookupError):
    """A contract name nothing defines.

    Named rather than falling back to an empty contract: an empty one has no
    marker, so every answer "fails to parse" and the case fails for a reason
    that has nothing to do with the answer. A case graded against a contract
    that does not exist is not evidence, and it must not look like it is.
    """


def verdict(text: str, name: str, config: dict | None = None):
    spec = contracts.contract(name, config)
    if not spec.get("marker"):
        raise UnknownContract(
            f"no contract called `{name}`. Known: "
            f"{', '.join(sorted(contracts.BUILT_IN))}, or define one in "
            "settings/contracts/")
    return contracts.read(text, spec)


# ------------------------------------------------------------- the four

def obeys_contract(output, arguments: dict) -> dict:
    """Did the answer obey its output contract at all.

    The weakest and most useful check: a phase whose format drifted is a phase
    whose every later answer reads as unparseable, and this catches it before a
    prompt change ships.
    """
    name = str(arguments.get("contract") or "verdict")
    answer = verdict(text_of(output), name, arguments.get("config"))

    unparseable = str(contracts.contract(name).get("unparseable") or "unreadable")
    passed = answer.value != unparseable
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (f"parsed as `{answer.value}`" if passed
                   else f"did not parse: {answer.why}"),
        "details": {"value": answer.value, "downgraded": answer.downgraded,
                    "downgraded_from": answer.downgraded_from},
    }


def verdict_is(output, arguments: dict) -> dict:
    """Did it reach the answer this case expects.

    **Graded after the contract's downgrades, not before.** A `PROVEN: yes` with
    no evidence is `unproven`, and a case expecting `yes` should fail on it —
    grading the raw claim would reward exactly the behaviour the contract exists
    to catch.
    """
    name = str(arguments.get("contract") or "verdict")
    expected = arguments.get("equals") or arguments.get("in") or []
    expected = [expected] if isinstance(expected, str) else list(expected)
    expected = [str(v).lower() for v in expected]

    answer = verdict(text_of(output), name, arguments.get("config"))
    passed = answer.value in expected
    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": (f"answered `{answer.value}`" if passed
                   else f"answered `{answer.value}`, expected "
                        f"{' or '.join(f'`{v}`' for v in expected)}"),
        "details": {"value": answer.value, "expected": expected,
                    "downgraded_from": answer.downgraded_from},
    }


def mentions(output, arguments: dict) -> dict:
    """Did it name the thing this case is about.

    `any` for "found at least one of these", `all` for "found every one",
    `none` for "said none of these". Matched case-insensitively as substrings
    unless `regex` is set, because a case author writing `Decimal` should not
    have to think about word boundaries.
    """
    text = text_of(output)
    haystack = text if arguments.get("case_sensitive") else text.lower()

    def present(needle: str) -> bool:
        if arguments.get("regex"):
            flags = 0 if arguments.get("case_sensitive") else re.IGNORECASE
            return bool(re.search(needle, text, flags))
        return (needle if arguments.get("case_sensitive") else needle.lower()) in haystack

    wanted_any = [str(v) for v in (arguments.get("any") or [])]
    wanted_all = [str(v) for v in (arguments.get("all") or [])]
    unwanted = [str(v) for v in (arguments.get("none") or [])]

    found_any = [v for v in wanted_any if present(v)]
    missing_all = [v for v in wanted_all if not present(v)]
    found_unwanted = [v for v in unwanted if present(v)]

    passed = ((not wanted_any or bool(found_any))
              and not missing_all and not found_unwanted)

    why = []
    if wanted_any and not found_any:
        why.append(f"none of {wanted_any} appear")
    if missing_all:
        why.append(f"missing {missing_all}")
    if found_unwanted:
        why.append(f"should not mention {found_unwanted}")

    return {
        "passed": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "; ".join(why) or "said what the case expects",
        "details": {"found_any": found_any, "missing": missing_all,
                    "unwanted": found_unwanted},
    }


def cites_evidence(output, arguments: dict) -> dict:
    """Did a claim of success carry a command under it.

    Evidence or it did not happen. This is the single most useful eval on a
    `prove` phase, because a model that stops running things and starts
    asserting them still produces output that reads exactly like a proof.
    """
    text = text_of(output)
    answer = verdict(text, str(arguments.get("contract") or "proven"))
    least = int(arguments.get("at_least") or 1)

    passed = len(answer.evidence) >= least and not answer.downgraded
    return {
        "passed": passed,
        "score": min(1.0, len(answer.evidence) / max(least, 1)),
        "reason": (f"{len(answer.evidence)} command(s) cited"
                   if passed else
                   (answer.why or f"{len(answer.evidence)} command(s), "
                                  f"expected at least {least}")),
        "details": {"commands": list(answer.evidence[:10]),
                    "value": answer.value,
                    "downgraded_from": answer.downgraded_from},
    }


# The names the eval worker calls, and what each is for.
EVALUATORS = {
    "contract": (obeys_contract,
                 "Did the answer obey its output contract at all"),
    "verdict-is": (verdict_is,
                   "Did it reach the expected answer, after any downgrade"),
    "mentions": (mentions,
                 "Did it name the thing this case is about"),
    "cites-evidence": (cites_evidence,
                       "Did a claim of success carry a command under it"),
}


def run(name: str, payload: dict) -> dict:
    """Dispatch one evaluator from an `eval::*` invocation.

    An unknown name fails rather than passing. An evaluator that cannot run is
    not evidence of anything, and reporting it as a pass would put a green tick
    on a case nobody graded.
    """
    entry = EVALUATORS.get(name)
    if entry is None:
        return {"passed": False, "score": 0.0,
                "reason": f"no evaluator called `{name}`. "
                          f"Known: {', '.join(sorted(EVALUATORS))}"}

    data = payload.get("payload") or payload
    try:
        return entry[0](data.get("output"), dict(data.get("arguments") or {}))
    except UnknownContract as exc:
        return {"passed": False, "score": 0.0, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        # A broken evaluator is a failed case, never a passing one, for the same
        # reason a predicate that raises is a finding.
        return {"passed": False, "score": 0.0,
                "reason": f"the evaluator raised {type(exc).__name__}: {exc}"}
