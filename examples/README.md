# Two configurations, at opposite ends

Neither is a starting point you have to take. `settings/` is empty on purpose
and ghola runs on its built-in defaults, which sit between these two. These
exist to show the range: the same pipeline, configured for a repository nobody
can afford to break and for one nobody has to review.

Copy the files from one into `settings/`, or copy the lines you want. Nothing
here is loaded from this directory — it is example text, and `make config`
prints what is actually in effect.

| | `strict/` | `minimal/` |
|---|---|---|
| Stages | every check on, and one more | `run` and `publish` |
| Oversight | `attended` — a person answers every write | `dark` — nothing waits |
| Revisions | 3 | 0 |
| A turn may | read, edit, run tests | read, edit, run tests |
| Costs | four turns per job, two on a thinking model | one turn per job |
| For | a repository with users on it | a scratch repo, a spike, a migration |

## Reading them in the right order

**Start from `minimal/` if you are trying ghola out.** One turn, no checks, a
request in a file, no forge account. It is the shortest path from a spec to a
diff you can read, and what it leaves out is exactly what makes the strict one
slow.

**Read `strict/` before turning anything off.** Every stage in it is there
because something got through without it, and each file says which. That is
more useful than the list of settings.

## What neither of them changes

The oversight dial does not go where a rule marked `ask` becomes `allow`, at
any level, including `dark`. An unattended factory reading "ask" as "yes" has
answered a question nobody put.

Nothing merges itself in either configuration. `minimal/` still opens a request
and still stops, because the point of the gate is not how much was checked
before it — it is that a person decides.
