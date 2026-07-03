# Feature implementation loop

Use this for new behavior, product changes, API additions, and user-visible improvements.

## Step 1 — Understand the requested behavior

Identify:

- user-visible goal,
- inputs and outputs,
- existing related behavior,
- compatibility constraints,
- data or API changes,
- acceptance criteria.

Search for existing patterns before creating new ones.

## Step 2 — Design the smallest implementation

Prefer extending an existing path over creating a parallel system.

Plan:

- files to change,
- tests to add or update,
- docs to update,
- risks and rollback considerations.

Avoid speculative infrastructure. Do not build for hypothetical future requirements.

## Step 3 — Implement incrementally

- Start with core logic.
- Then wire integration points.
- Then update tests.
- Then update docs if behavior changed.
- Keep commits or edits logically grouped even if you do not commit.

## Step 4 — Test behavior

Add or update tests for:

- happy path,
- important edge cases,
- invalid input or failure handling,
- compatibility behavior if relevant.

Run focused checks first, then broader checks when appropriate.

## Step 5 — Review feature risk

Check for:

- public API compatibility,
- schema or migration impact,
- authorization and privacy impact,
- performance impact,
- accessibility or localization impact for UI,
- observability or logging needs,
- docs impact.

## Final response

Include:

- implemented behavior,
- files changed,
- tests and checks run,
- docs updated or reason not needed,
- assumptions and remaining risks.
