"""One table for what a tool is called on each side of the fence.

A repository that already uses Claude Code writes `Bash` and `Write` in its
`settings.json`. An iii engine registers `shell::exec` and `coder::create-file`.
They are the same capabilities under two vocabularies, and a rule withholding
`Write` from a phase granted `coder::create-file` takes nothing away unless
something knows they are the same thing.

Keeping that knowledge in one table is the point. wipp had this split across a
matcher and a grant that agreed only because somebody kept them agreeing, and
the day they stopped agreeing the rule silently enforced nothing.

The mapping is deliberately incomplete. A name that reaches no function is
reported rather than guessed at, because a guess here is a rule that looks
enforced and is not.
"""

from __future__ import annotations

import fnmatch

# Claude Code's tool names, and the iii functions that do the same job.
# One name may reach several functions: `Bash` is both the foreground and the
# background runner, and withholding it has to take both.
EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "Bash": ("shell::exec", "shell::exec_bg", "shell::kill", "shell::status"),
    "Read": ("coder::read-file", "shell::fs::read"),
    "Write": ("coder::create-file", "shell::fs::write"),
    "Edit": ("coder::update-file", "shell::fs::sed"),
    "MultiEdit": ("coder::update-file",),
    "NotebookEdit": ("coder::update-file",),
    "Glob": ("coder::list-folder", "coder::tree", "shell::fs::ls"),
    "Grep": ("coder::search", "shell::fs::grep"),
    "LS": ("coder::list-folder", "shell::fs::ls"),
    "WebFetch": ("web::fetch", "scrapling::fetch"),
    "WebSearch": ("web::search",),
    "Task": ("harness::spawn",),
}

# The other direction, built once. A function may answer to one name only, so
# the first match wins and the table above is the place to change it.
CANONICAL: dict[str, str] = {
    function_id: name
    for name, functions in EQUIVALENTS.items()
    for function_id in functions
}


def functions_for(name: str) -> tuple[str, ...]:
    """Every function a tool name reaches.

    A name already in `worker::function` form is returned as itself, so a
    repository may name an iii function directly and does not have to learn this
    table to withhold something.
    """
    name = name.strip()
    if "::" in name:
        return (name,)
    return EQUIVALENTS.get(name, ())


def name_for(function_id: str) -> str:
    """What Claude Code calls this function, or the function id itself."""
    return CANONICAL.get(function_id, function_id)


def matches(pattern: str, function_id: str, arguments: dict | None = None) -> bool:
    """Whether a permission entry is about this call.

    Two shapes, and they mean different things:

    - `Bash` names a whole tool. It matches every call to it.
    - `Bash(php *)` names an ARGUMENT. It matches only calls whose command looks
      like that.

    The argument pattern is `fnmatch`, plus a bare prefix treated as one. **It
    does not parse the shell.** `make test && php artisan migrate` does not match
    `php *` and is not refused, for the same reason a rung-3 callback does not
    guess what `sed -i` will write: a matcher that tried would be a different
    rule wearing this one's authority.
    """
    pattern = pattern.strip()
    tool, _, argument = pattern.partition("(")
    argument = argument.rstrip(")")

    if function_id not in functions_for(tool.strip()) and tool.strip() != function_id:
        return False
    if not argument:
        return True

    subject = command_of(arguments or {})
    if not subject:
        return False
    return fnmatch.fnmatch(subject, argument) or fnmatch.fnmatch(subject, f"{argument}*")


# Where the thing a permission entry is about actually lives in the arguments.
SUBJECT_KEYS = ("command", "cmd", "script", "path", "file", "file_path", "url")


def command_of(arguments: dict) -> str:
    """The string a permission entry's argument pattern is matched against."""
    for key in SUBJECT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def unresolved(names: list[str]) -> list[str]:
    """Names that reach no function at all.

    A withheld name that reaches nothing is a rule enforcing nothing, and it
    fails silently in exactly the way this whole model exists to prevent. So it
    is reported rather than ignored.
    """
    return [n for n in names if not functions_for(n.split("(")[0].strip())]
