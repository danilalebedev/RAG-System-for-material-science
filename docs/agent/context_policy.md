# Context policy

Use this when deciding what context to load and how much to read before editing.

## Context loading principles

- Load the smallest context that can answer the task safely.
- Prefer repository evidence over guesses.
- Prefer nearby code and tests over global search when the likely area is known.
- Avoid reading large files fully unless necessary.
- Stop searching when evidence is sufficient to make a safe minimal change.

## Search strategy

Start with:

- exact error messages,
- function/class names,
- route names,
- test names,
- public symbols,
- config keys.

Use `rg` before slower tools.

## What to inspect

For a code change, usually inspect:

- target file,
- tests for target file,
- call sites,
- type definitions or interfaces,
- package scripts or CI commands for validation.

For bugs, inspect:

- failing test or reproduction,
- stack trace location,
- adjacent tests,
- recent equivalent patterns.

For features, inspect:

- existing analogous features,
- routing or integration points,
- tests for analogous features,
- docs or API contracts.

## Context bloat avoidance

Do not paste or summarize huge unrelated sections into the working context. If context grows too large, write a short evidence summary with file paths and line references, then proceed.

## Evidence summary format

When helpful, use:

- `Evidence:` what was found,
- `Implication:` what it means,
- `Next:` what to edit or test.
