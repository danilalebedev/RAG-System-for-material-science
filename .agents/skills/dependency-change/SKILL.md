---
name: dependency-change
description: Use when adding, removing, upgrading, replacing, or auditing production or development dependencies, including lockfile updates.
---

Dependency changes are high risk. Use this workflow before editing dependency manifests or lockfiles.

Required behavior:

1. Identify why the dependency change is necessary.
2. Check whether existing dependencies or standard library features can solve the task.
3. Prefer minimal version changes.
4. Avoid broad upgrades unless explicitly requested.
5. Update the correct manifest and lockfile together.
6. Run install, tests, build, and security checks if available.
7. Report package names, version changes, rationale, validation, and risk.

Do not add a new production dependency without explaining why it is needed.
