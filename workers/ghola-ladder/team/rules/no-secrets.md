---
id: no-secrets
description: A credential never reaches a file
why: A leaked key costs a rotation, an incident review, and whatever was done with it before anyone noticed.
paths: ["**"]
escape: secret-ok
---

This ships at the team layer, so it travels to every repository the ladder runs
against, including ones with no configuration of their own. That is what makes it
a standard rather than a suggestion.

It is carried at rung 3 by default, because a team constraint with a script beside
it lands there. `ladder::move` can carry it at rung 4 as well, and it probably
should: rung 3 sees one call at a time and never sees inside a shell heredoc,
while rung 4 sees the finished diff.
