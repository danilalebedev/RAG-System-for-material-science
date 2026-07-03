---
name: test-generation
description: Use for adding tests, improving coverage, creating regression tests, selecting validation commands, or fixing weak/flaky tests.
---

Follow `docs/agent/testing_policy.md`.

Required behavior:

1. Identify the behavior under test.
2. Inspect existing test style and helpers.
3. Write deterministic tests that prove behavior.
4. Avoid real network calls, secrets, sleeps, and order-dependent behavior.
5. Ensure the test would fail without the intended change when feasible.
6. Run the focused test command.
7. Report commands and results.

Do not weaken assertions or delete failing tests without a clear reason.
