"""Job records. Files, deliberately.

**Why not the `state` worker**, when the rule everywhere else here is to prefer
one. Its `store_method` defaults to `in_memory`, which its own schema calls
"volatile, process-lifetime storage, lost on shutdown — not for production". It
persists correctly once configured, and I checked that it does; the problem is
not the worker.

The problem is the shape of the failure. A factory on the default adapter works
perfectly until the first restart, and the first restart is usually the one
during a long job. Nothing announces it. For a starter kit somebody clones and
points at their own repository, a store that silently loses every job because one
config key was missed is a worse trade than a store that is obviously a
directory.

So: one JSON file per job. It cannot be misconfigured, `cat state/jobs/<id>.json`
is a debugging tool, and a crash loses at most the write in flight.

The `state` worker is still installed and still configured `file_based`, because
`approval-gate`, `worktree` and `memory` all store through it and they should not
be on the volatile default either. This module is about ghola's own records.

Writes are atomic: a temporary file in the same directory, then `os.replace`,
which is atomic on POSIX. A half-written job record read by the reconciler is a
job in a state that never existed.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# What a job carries. Not a schema anybody validates against: a record is
# whatever the pipeline put on it, and this names the fields the graph and the
# reconciler read so a rename shows up here rather than in six call sites.
CORE_FIELDS = ("id", "spec", "repo", "stage", "reason", "revisions",
               "last_refusal", "created_at", "updated_at")


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> int:
    return int(time.time() * 1000)


@dataclass
class Store:
    """One directory of job records."""

    folder: Path

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    def path(self, job_id: str) -> Path:
        # The id is generated here and is always hex, but a path is built from
        # it and a caller could pass anything. Refusing a separator is cheaper
        # than explaining why a job wrote outside its directory.
        if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith("."):
            raise ValueError(f"not a job id: {job_id!r}")
        return self.folder / f"{job_id}.json"

    def create(self, spec: str, repo: str, stage: str, **fields) -> dict:
        job = {
            "id": new_id(),
            "spec": spec,
            "repo": repo,
            "stage": stage,
            "reason": "",
            "revisions": 0,
            "last_refusal": "",
            "created_at": now(),
            "updated_at": now(),
            "history": [],
            **fields,
        }
        self.write(job)
        return job

    def read(self, job_id: str) -> dict | None:
        try:
            return json.loads(self.path(job_id).read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def write(self, job: dict) -> dict:
        """Atomically. A half-written record is a job in a state that never was."""
        self.folder.mkdir(parents=True, exist_ok=True)
        job["updated_at"] = now()
        target = self.path(str(job["id"]))

        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.folder, prefix=f".{job['id']}.", suffix=".tmp",
            delete=False, encoding="utf-8")
        try:
            json.dump(job, handle, indent=2, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(handle.name, target)
        except BaseException:
            handle.close()
            Path(handle.name).unlink(missing_ok=True)
            raise
        return job

    def list(self) -> list[dict]:
        """Every job, newest first. Unreadable files are skipped, not fatal."""
        if not self.folder.is_dir():
            return []
        found = []
        for path in self.folder.glob("*.json"):
            try:
                found.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(found, key=lambda j: j.get("created_at", 0), reverse=True)

    def waiting(self) -> list[dict]:
        """Jobs the reconciler has to look at."""
        return [j for j in self.list() if j.get("stage") == "waiting"]


def advance(job: dict, to: str, why: str = "", revision: bool = False,
            **fields) -> dict:
    """Move a job to a stage, keeping the history.

    Pure: it returns the new record and writes nothing. The caller writes, which
    is what lets the whole state machine be tested against dicts.

    **Guarded on the job's own stage by the caller**, not here. At-least-once
    delivery means a stage can be handed the same job twice, and the guard is
    `job['stage'] == expected` at the point of dispatch.
    """
    moved = dict(job)
    moved["history"] = list(job.get("history") or []) + [{
        "from": job.get("stage"),
        "to": to,
        "why": why,
        "at": now(),
    }]
    moved["stage"] = to
    moved["updated_at"] = now()

    if revision:
        moved["revisions"] = int(job.get("revisions") or 0) + 1
        moved["reason"] = "revision"
    for key, value in fields.items():
        moved[key] = value
    return moved


def is_terminal(job: dict, terminal: tuple[str, ...]) -> bool:
    return str(job.get("stage") or "") in terminal


def summary(job: dict) -> dict:
    """What a dashboard row needs, without the whole record."""
    return {
        "id": job.get("id"),
        "spec": job.get("spec"),
        "repo": job.get("repo"),
        "stage": job.get("stage"),
        "revisions": job.get("revisions", 0),
        "steps": len(job.get("history") or []),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
