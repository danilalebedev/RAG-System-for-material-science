# Security review playbook

Use this for vulnerability fixes, auth/authz changes, secrets, crypto, command execution, file upload, parsing, dependency changes, and any security-sensitive code path.

## Security-sensitive areas

Treat these as high risk:

- authentication and sessions,
- authorization and access control,
- secrets and credentials,
- payments and billing,
- PII and sensitive data,
- SQL/query construction,
- command execution,
- deserialization and parsing,
- file upload and path handling,
- SSRF and outbound requests,
- XSS, CSRF, redirects, CORS,
- cryptography and signing,
- dependency updates,
- audit logs and telemetry.

## Review steps

1. Identify the asset or trust boundary.
2. Identify attacker-controlled inputs.
3. Trace data flow from input to sink.
4. Check existing controls and whether they are preserved.
5. Patch the smallest vulnerable path.
6. Add tests for exploit and safe behavior when feasible.
7. Validate that the fix does not weaken other protections.

## Patch rules

- Do not bypass authorization to make functionality work.
- Do not log secrets, tokens, passwords, private keys, or full PII.
- Do not weaken validation or sanitization without replacement controls.
- Do not add shell execution or dynamic evaluation unless explicitly required.
- Prefer allowlists over denylists for dangerous inputs.
- Prefer parameterized queries over string construction.
- Prefer constant-time comparison for secrets when relevant.
- Prefer least privilege for tokens, scopes, permissions, and files.

## Testing

Add tests for:

- blocked malicious input,
- allowed legitimate input,
- authorization failure,
- regression of the original issue.

Do not include real secrets in tests. Use placeholders.

## Final response

Include:

- risk addressed,
- files changed,
- validation run,
- security assumptions,
- residual risk.
