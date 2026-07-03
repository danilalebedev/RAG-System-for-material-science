# Testing policy

Use this for writing, updating, selecting, and running tests.

## Principles

- Tests should prove behavior, not implementation details.
- Prefer focused tests that fail before the fix and pass after it.
- Avoid brittle sleeps, real network calls, real credentials, and dependence on test order.
- Use existing test style and helpers.
- Do not weaken assertions to make tests pass.
- Do not delete failing tests unless they are obsolete and the reason is clear.

## When to add tests

Add or update tests when:

- fixing a bug,
- adding behavior,
- changing public API behavior,
- touching security-sensitive logic,
- changing parsing, validation, auth, serialization, migrations, concurrency, or error handling.

It is acceptable not to add tests when:

- the change is documentation-only,
- the change is a trivial mechanical rename covered by existing tests,
- the repository has no practical test harness for the touched area,
- adding a test would require unrelated infrastructure.

If no test is added, explain why.

## Test selection order

1. Run the exact failing test or reproduction.
2. Run tests for the touched file/module/package.
3. Run integration tests for affected flows.
4. Run lint/typecheck/build when relevant.
5. Run the full suite for cross-cutting or high-risk changes.

## Test-writing checklist

For each new or changed test, check:

- It would fail without the code change.
- It covers the requested behavior or regression.
- It uses deterministic fixtures.
- It avoids unnecessary mocking when real local behavior is cheap.
- It does not require internet or secrets.
- It follows existing naming and organization.

## Reporting validation

Always report:

- exact command run,
- pass/fail result,
- if failed, the meaningful error summary,
- commands not run and why.

Never claim tests passed unless they were actually run.
