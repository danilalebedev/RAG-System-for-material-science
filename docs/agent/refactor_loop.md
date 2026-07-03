# Refactor safety loop

Use this for refactors, cleanup, module moves, renames, and internal restructuring.

## Refactor rule

A refactor must preserve externally observable behavior unless the user explicitly requests a behavior change.

## Step 1 — Establish behavior baseline

Before editing:

- identify the public surface and callers,
- identify tests that protect current behavior,
- run focused baseline tests when feasible,
- inspect APIs, serialization formats, migrations, and config.

## Step 2 — Bound the refactor

State:

- what will change structurally,
- what must not change behaviorally,
- which files are in scope,
- which files are out of scope.

Avoid mixing refactor with feature work.

## Step 3 — Make mechanical changes first

Prefer safe mechanical steps:

- rename symbol,
- move file,
- update imports,
- extract function,
- remove duplication.

Keep logic changes separate from mechanical changes.

## Step 4 — Validate equivalence

Run:

1. focused tests for touched modules,
2. typecheck or compiler,
3. lint/format if relevant,
4. broader suite if cross-cutting.

Compare behavior when a reproduction or snapshot exists.

## Step 5 — Review risk

Check:

- public exports,
- serialization and database compatibility,
- import cycles,
- dead code removal mistakes,
- performance-sensitive paths,
- concurrency/state changes.

## Final response

Include:

- refactor scope,
- behavior-preservation strategy,
- files changed,
- validation run,
- risks.
