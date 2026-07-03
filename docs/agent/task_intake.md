# Task intake playbook

Use this playbook when the task is broad, ambiguous, cross-cutting, or under-specified.

## Intake checklist

Identify four fields before editing:

1. Goal — what outcome is requested.
2. Context — relevant files, tests, errors, tickets, docs, logs, examples, and constraints.
3. Assumptions — what is unknown and what safe assumptions can be made.
4. Done when — concrete success criteria.

## Clarification policy

Ask one targeted question only when:

- the ambiguity materially changes the implementation,
- no safe default exists,
- the task is interactive.

Do not ask a question when:

- a safe reversible next step exists,
- the user asked for best effort,
- the task is non-interactive,
- the missing detail can be discovered from the repository.

## Planning policy

For tasks spanning more than one file, create a short plan before editing:

- files or modules to inspect,
- expected change area,
- validation approach,
- risks.

Keep the plan short. Revise it when evidence invalidates it.

## Evidence policy

Do not rely on memory when repository evidence is available.

Prefer:

- `rg` search results,
- package scripts,
- CI files,
- tests,
- nearby implementations,
- type definitions,
- docs in the repo.

## Output

Before editing, write a short note internally or in the task thread:

- "I will inspect X and Y, then patch the smallest responsible area and run Z."

After editing, report:

- assumption made,
- changed files,
- validation,
- unresolved questions.
