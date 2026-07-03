# Code review checklist

Use this for reviewing a diff, pull request, commit, or uncommitted changes.

Review the change as production code. Focus on correctness, safety, maintainability, and missing validation.

## Review process

1. Understand the requested behavior or PR goal.
2. Inspect the diff.
3. Inspect nearby code when needed.
4. Identify concrete risks.
5. Prefer fewer, higher-signal findings.
6. Suggest specific fixes.

## Findings to prioritize

Look for:

- incorrect behavior against requirements,
- regressions in adjacent flows,
- missing tests for changed behavior,
- over-broad or unrelated changes,
- accidental public API changes,
- security or privacy issues,
- auth/permission bypasses,
- data migration or compatibility issues,
- concurrency, caching, lifecycle, or state bugs,
- error handling gaps,
- performance risks in hot paths,
- dependency or lockfile risks,
- flaky or weak tests,
- generated files updated incorrectly.

## Finding format

For each finding, include:

- severity: `blocker`, `important`, or `minor`,
- file and location,
- issue,
- why it matters,
- suggested fix.

Use concise, actionable language.

## Non-findings

Do not report:

- pure style preferences already handled by formatters,
- hypothetical issues with no plausible path,
- requests for broad rewrites unrelated to the change,
- compliments as findings.

## Final review summary

End with:

- overall risk level,
- whether tests seem adequate,
- any validation still needed.

If no major issues are found, say so clearly and mention residual risks.
