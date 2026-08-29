# Document the ports each service uses

## What

`docker-compose.yml` maps ports for the database, the backend and the frontend,
but `README.md` never says which port a developer should open after `make up`.

Add a short section to `README.md` naming each service and the port it is
reachable on, read from `docker-compose.yml` rather than guessed.

## Why

The first thing anyone does after starting the stack is try to open it, and
today that means reading the compose file to find out where.

## Acceptance criteria

- `README.md` gains a section listing each service and its port.
- The ports match `docker-compose.yml` exactly. Do not invent a service that is
  not there.
- Nothing outside `README.md` changes.

## Out of scope

Do not change `docker-compose.yml`. Do not restructure the rest of the README.
