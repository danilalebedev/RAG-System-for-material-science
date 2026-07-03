---
name: refactor-safety
description: Use for refactors, cleanup, code moves, renames, extraction, deduplication, and internal restructuring where behavior should stay the same.
---

Follow `docs/agent/refactor_loop.md`.

Required behavior:

1. Establish current behavior and public surface.
2. Bound the refactor scope.
3. Keep behavior changes separate from mechanical changes.
4. Preserve public APIs and serialized formats unless explicitly requested.
5. Run focused tests and type/lint/build checks as relevant.
6. Inspect import cycles, dead code removal, and compatibility risks.
7. Report behavior-preservation strategy and validation.

Do not mix refactor with feature work unless explicitly requested.
