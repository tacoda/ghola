"""The settings, read from `settings/phases.yaml` if it exists at all.

One place turns a phase name into the options a `harness::send` carries. There is
no logic here beyond merging a phase's block over the defaults, which is the
point: a change that is a number or a name belongs in the YAML, and a change that
needs a branch belongs in a callback.

**The file is optional.** With no `settings/phases.yaml`, every phase in
`defaults.PHASES` still works. What the file does is override, key by key, and a
team that agrees with the built-ins writes nothing. That is the whole of
convention over configuration here: the convention is a value, not an absence.

Read fresh on every call rather than cached at import, so editing the file
changes the next turn without restarting a worker. That is the same contract
iii's configuration worker gives every other worker in this system.
"""

import yaml

import defaults
import paths

# Only keys the harness worker's own schema names are passed through. A typo in
# the YAML should surface as a missing setting rather than travel to the harness
# as an unknown field, where it is ignored and the phase quietly runs on a
# default nobody chose.
SEND_OPTIONS = (
    "functions",
    "max_turns",
    "max_cost_usd",
    "max_total_tokens",
    "max_output_tokens",
    "thinking_level",
    "output",
    "system_prompt",
    "system_prompt_strategy",
    "max_validation_retries",
)


def declared() -> dict:
    """Whatever `settings/phases.yaml` says, or an empty shape.

    A missing file is the normal case and not an error. A malformed one is also
    read as empty, which means a YAML syntax error falls back to the built-ins
    rather than stopping the factory. `ghola config` is where that becomes
    visible, because a silent fallback nobody can see is the failure this whole
    design is against.
    """
    try:
        return yaml.safe_load(paths.settings("phases.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}


def load() -> dict:
    """The effective configuration: the file merged over the built-in defaults.

    Merged one level down, so a file that sets `plan.max_turns` keeps the built-in
    model and grant for `plan` rather than replacing the whole block. A phase the
    file names and the defaults do not is simply added.
    """
    config = defaults.config()
    given = declared()

    config["defaults"].update(given.get("defaults") or {})
    for name, block in (given.get("phases") or {}).items():
        config["phases"].setdefault(name, {}).update(block or {})
    return config


def for_phase(phase: str, config: dict | None = None) -> dict:
    """The settings for one phase: its own block over the defaults.

    `functions` is replaced wholesale rather than merged, because a phase that
    lists its own tools means those and not those-plus-the-defaults. Rung 1 read
    as an accident of merge order is how a check ends up holding an editor.
    """
    config = load() if config is None else config
    settings = dict(config.get("defaults") or {})
    settings.update((config.get("phases") or {}).get(phase) or {})
    return settings


def send_options(phase: str, config: dict | None = None) -> dict:
    """What goes under `options` in a `harness::send`, and nothing else."""
    settings = for_phase(phase, config)
    return {key: settings[key] for key in SEND_OPTIONS if key in settings}


def model_for(phase: str, requested: str = "", config: dict | None = None) -> str:
    """The model this phase runs on: what the caller asked for, else the setting.

    The caller's model wins because `repos.toml` is where an operator says what a
    repository's work is worth. The setting is the default, not the authority.
    """
    return requested or str(for_phase(phase, config).get("model") or "")


def phases(config: dict | None = None) -> list[str]:
    """Every phase there is, built in or declared. `make turn` uses it to reject a
    typo with the list rather than starting a turn on the bare defaults."""
    config = load() if config is None else config
    return sorted((config.get("phases") or {}).keys())


def provenance(phase: str) -> dict[str, str]:
    """Where each of this phase's settings came from: `built-in` or `settings`.

    A default nobody can see is a magic number, so this is what `ghola config`
    prints. It is here rather than in the CLI because the merge order is the
    thing being reported, and the merge order lives in this file.
    """
    given = declared()
    from_file = dict(given.get("defaults") or {})
    from_file.update((given.get("phases") or {}).get(phase) or {})
    return {key: ("settings" if key in from_file else "built-in")
            for key in sorted(for_phase(phase))}
