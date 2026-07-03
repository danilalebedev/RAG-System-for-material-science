---
name: feature-implementation
description: Use for implementing a new feature, product behavior, public API addition, or user-visible behavior change. Do not use for pure bug fixes or refactors.
---

Follow `docs/agent/feature_loop.md`.

Required behavior:

1. Identify the requested behavior and acceptance criteria.
2. Search for existing analogous implementations.
3. Plan the smallest implementation.
4. Implement incrementally.
5. Add or update tests when feasible.
6. Update docs when behavior, setup, or public API changes.
7. Validate with focused checks.
8. Report assumptions, changed files, tests, and risks.

Avoid speculative architecture and unused extension points.
