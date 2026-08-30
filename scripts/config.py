"""Print the effective settings, and where each value came from.

Configuration is optional in ghola, which only works if the defaults are
visible. A value nobody can see is a magic number, and a fallback nobody can see
is worse: a malformed `settings/phases.yaml` is read as absent, so without this
command a YAML syntax error looks exactly like agreeing with the built-ins.

    make config              every phase
    make config PHASE=plan   one of them
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workers" / "ghola-core" / "src"))

import paths  # noqa: E402
import phase_settings  # noqa: E402


def show(phase: str) -> None:
    settings = phase_settings.for_phase(phase)
    source = phase_settings.provenance(phase)
    print(f"\n{phase}")
    for key in sorted(settings):
        value = settings[key]
        if key == "functions":
            allowed = (value or {}).get("allow") or []
            value = f"{len(allowed)} allowed: {', '.join(allowed[:3])}…"
        print(f"  {key:24} {str(value)[:72]:74} [{source[key]}]")


def show_evals() -> None:
    """Which cases and graders are in effect.

    A team's suite lives outside this repository, so the only way to know ghola
    can see it is to ask. A suite that moved contributes no cases, and a run of
    no cases prints exactly like a run that passed.
    """
    import yaml

    import evals
    try:
        config = yaml.safe_load(paths.settings("evals.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        config = {}

    found = evals.gather(config, paths.root())
    print(f"evals    : {len(found.cases)} case(s) in "
          f"{len(evals.places(config, paths.root()))} suite(s)")
    for problem in found.problems:
        print(f"  WARNING: {problem}")

    named = evals.graders(config)
    if named:
        # Listed rather than verified. Whether the function exists is the
        # engine's answer, and this command deliberately needs no connection.
        print(f"graders  : {', '.join(named)}")


def main() -> int:
    given = paths.settings("phases.yaml")
    print(f"root     : {paths.root()}")
    print(f"settings : {given}" + ("" if given.exists() else "  (absent, using built-ins)"))
    if given.exists() and not phase_settings.declared():
        # The one failure this command exists to make loud.
        print("  WARNING: the file exists and parsed to nothing. A YAML error here")
        print("           is silently identical to having no file at all.")

    import prompts
    have = prompts.declared()
    known_phases = phase_settings.phases()
    missing = [p for p in known_phases if p not in have]
    print(f"prompts  : {len(have)} of {len(known_phases)} phases"
          + (f"  (no prompt for: {', '.join(missing)})" if missing else ""))

    show_evals()

    wanted = [a for a in sys.argv[1:] if a]
    known = phase_settings.phases()
    for phase in wanted or known:
        if phase not in known:
            print(f"\nno phase {phase!r}. Known: {', '.join(known)}")
            return 2
        show(phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
