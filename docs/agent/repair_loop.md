# Repair loop

Use this for bugs, failing tests, regressions, broken examples, flaky behavior, and broken CI.

## Step 1 — Review without editing

- Restate the failure or requested fix.
- Identify the exact command, test, log, stack trace, ticket, or behavior.
- Inspect relevant files, tests, and nearby code.
- Check recent patterns and existing conventions.
- Do not edit during this step unless the fix is obvious, isolated, and safe.

## Step 2 — Reproduce or simulate

Prefer direct reproduction:

- run the failing test,
- run the reported command,
- inspect the failing code path,
- add a minimal temporary reproduction only if needed.

If reproduction is not possible, explain why and proceed from available evidence.

## Step 3 — Localize

Write a short localization note:

- likely file or function,
- why it is responsible,
- evidence supporting the hypothesis,
- what validation will confirm the fix.

Localize before patching. Do not change broad areas to "see what happens."

## Step 4 — Patch minimally

- Make the smallest patch that fixes the localized cause.
- Preserve behavior outside the failing path.
- Avoid unrelated refactors.
- Avoid dependency changes.
- Add or update a regression test when feasible.

## Step 5 — Validate

Run checks in this order:

1. original failing command or focused reproduction,
2. touched module tests,
3. related integration tests,
4. lint/typecheck/build when relevant,
5. broader suite if the risk is cross-cutting.

If the first patch fails, use the failure output as new evidence. Do not blindly stack patches.

## Step 6 — Review and report

Final response must include:

- root cause,
- fix summary,
- files changed,
- validation commands and results,
- regression test added or reason not added,
- remaining risks.
