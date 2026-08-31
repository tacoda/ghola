"""A primitive file into a `Primitive`. Markdown with YAML frontmatter.

Kept separate from `load.py` because parsing text is pure and reading a directory
is not. Every test about what a primitive *means* runs against this module with a
string, and no test needs a temporary directory to ask a question about syntax.

**Most of the axes are not in the frontmatter.** `kind` comes from the directory,
`side` follows from the kind, `direction` follows from whether a script sits
beside the file, and a capability's `rung` is its layer. What a file may declare
is what a directory cannot say: its description, its `why`, the paths it governs,
its policy, and a `rung:` when it departs from the default for its level.
"""

from __future__ import annotations

import yaml

from primitive import LAYERS, LadderError, Primitive, rung_number

FENCE = "---"


def split(text: str) -> tuple[dict, str]:
    """Frontmatter and body.

    A file with no frontmatter is not an error: it is a primitive with an empty
    header, which `validate` then reports as missing a `why`. Failing here would
    turn one malformed file into a stack trace with no name in it.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return {}, text.strip()

    for index in range(1, len(lines)):
        if lines[index].strip() == FENCE:
            try:
                loaded = yaml.safe_load("\n".join(lines[1:index])) or {}
            except yaml.YAMLError as exc:
                raise LadderError(f"the frontmatter is not valid YAML: {exc}") from exc
            if not isinstance(loaded, dict):
                raise LadderError("the frontmatter must be a mapping")
            return loaded, "\n".join(lines[index + 1:]).strip()

    raise LadderError("the frontmatter opens with --- and never closes")


def as_tuple(value) -> tuple[str, ...]:
    """One string or a list of them, always a tuple.

    `paths: "workers/**"` and `paths: ["workers/**"]` mean the same thing, and an
    author should not have to remember which the parser wanted.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    return tuple(str(item) for item in value if str(item).strip())


def parse(text: str, *, kind: str = "rule", layer: str = "project",
          source: str = "", script: str = "") -> Primitive:
    """One primitive file.

    `kind`, `layer` and `script` come from the caller, because they are facts
    about where the file sits rather than claims the file makes. A `layer:` in
    the frontmatter overrides the directory, which is the one departure worth
    allowing: a rule may be written down in one place and owned by another.
    """
    header, body = split(text)

    declared = str(header.get("layer") or layer).strip().lower()
    narrowed_from = ""
    if declared not in LAYERS:
        # There are three layers and there is no fourth. A repository writing
        # `layer: personal` is describing one person's preference, which this
        # model does not carry. It is read as `project`, which governs only the
        # repository it is in, AND IT IS TOLD SO. The narrow reading is chosen
        # deliberately, and the point of choosing it is that somebody can see it
        # was chosen.
        narrowed_from, declared = declared, "project"

    grades = str(header.get("grades") or "").strip()
    provisional = Primitive(
        id=str(header.get("id") or "").strip(),
        kind=kind,
        layer=declared,
        description=str(header.get("description") or "").strip(),
        why=str(header.get("why") or "").strip(),
        body=body,
        script=script,
        grades=grades,
        policy=str(header.get("policy") or "refuse").strip().lower(),
        paths=as_tuple(header.get("paths")),
        functions=as_tuple(header.get("functions")),
        withholds=as_tuple(header.get("withholds")),
        escape=str(header.get("escape") or "").strip(),
        locked=bool(header.get("locked")),
        implements=str(header.get("implements") or "").strip(),
        source=source,
        narrowed_from=narrowed_from,
    )

    # The rung is derived unless the file departs from the default. Writing
    # `rung:` is how you depart, and the departure is reported rather than
    # buried: `declared_rungs` is what a listing marks with a dagger.
    if header.get("rung") is None:
        from primitive import default_rungs
        rungs = default_rungs(provisional.layer, provisional.side,
                              bool(script or grades))
        declared_rungs = False
    else:
        value = header["rung"]
        values = value if isinstance(value, (list, tuple)) else [value]
        rungs = tuple(sorted({rung_number(v, provisional.side) for v in values}))
        declared_rungs = True

    return Primitive(**{**provisional.__dict__,
                        "rungs": rungs, "declared_rungs": declared_rungs})


def unparse(p: Primitive) -> str:
    """A primitive back to its file, preserving the body.

    Used by the lifecycle. Rewriting the whole file from the parsed primitive
    rather than editing the number with a regex, because a regex is how a rung
    ends up changed in the file and not in the generated hook.

    A derived rung is not written back. Writing it would turn every promotion
    into a permanent departure from the default, and the dagger in a listing
    would stop meaning anything.
    """
    header = {"id": p.id}
    for key, value in (("description", p.description), ("why", p.why)):
        if value:
            header[key] = value
    header["layer"] = p.layer
    if p.declared_rungs:
        header["rung"] = list(p.rungs) if len(p.rungs) > 1 else p.rungs[0]
    if p.side == "constraint" and p.policy != "refuse":
        header["policy"] = p.policy
    for key, value in (("paths", p.paths), ("functions", p.functions),
                       ("withholds", p.withholds)):
        if value:
            header[key] = list(value)
    for key, value in (("escape", p.escape), ("implements", p.implements),
                       ("grades", p.grades)):
        if value:
            header[key] = value
    if p.locked:
        header["locked"] = True

    front = yaml.safe_dump(header, sort_keys=False, default_flow_style=False).strip()
    return f"{FENCE}\n{front}\n{FENCE}\n\n{p.body}\n" if p.body else f"{FENCE}\n{front}\n{FENCE}\n"
