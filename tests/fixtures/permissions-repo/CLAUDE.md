# A repository that forbids one command

This repository's `.claude/settings.json` denies `Bash(rm *)`. It was written for
Claude Code and ghola honours it without the repository having to say it twice.

`rm` names an argument rather than a whole tool, so it is carried at rung 2: the
shell is still available and the matching call is refused.
