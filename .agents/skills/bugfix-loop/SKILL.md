---
name: bugfix-loop
description: Use for bug fixes, failing tests, regressions, broken examples, broken CI, and issues that require root-cause localization before patching. Do not use for greenfield features.
---

Follow `docs/agent/repair_loop.md`.

Required behavior:

1. Review the failure before editing.
2. Reproduce or inspect the exact failing path when feasible.
3. Localize the smallest responsible file/function.
4. Make the smallest safe patch.
5. Add or update a regression test when feasible.
6. Run focused validation first.
7. Inspect the diff.
8. Report root cause, files changed, validation, and remaining risk.

Do not:

- perform broad refactors,
- change unrelated files,
- weaken tests,
- claim validation passed unless it ran successfully.
