---
name: security-review
description: Use for vulnerability fixes, auth/authz, secrets, crypto, command execution, file upload, parsing, dependency changes, and security-sensitive code review.
---

Follow `docs/agent/security_review.md`.

Required behavior:

1. Identify trust boundaries and attacker-controlled inputs.
2. Trace data flow to sensitive sinks.
3. Preserve or strengthen existing controls.
4. Patch the smallest vulnerable path.
5. Add exploit/regression tests when feasible.
6. Never log secrets or weaken authorization/validation.
7. Report the risk addressed, validation, assumptions, and residual risk.

When uncertain, prefer conservative behavior and call out the uncertainty.
