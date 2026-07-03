---
name: code-review
description: Use when asked to review a diff, pull request, commit, or uncommitted changes for bugs, regressions, missing tests, security issues, and risky patterns.
---

Follow `docs/agent/code_review.md`.

Review rules:

1. Understand the PR or change goal.
2. Inspect the diff and nearby code when needed.
3. Focus on actionable correctness, safety, and validation issues.
4. Prefer fewer high-signal findings over many low-value comments.
5. Include severity, location, issue, impact, and suggested fix.
6. Call out missing tests or validation.
7. If no major issues are found, say so clearly and mention residual risks.

Do not review only style unless style causes real risk.
