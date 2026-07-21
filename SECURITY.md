# Security Policy

## Disclaimer

Community-maintained open-source project. **Not affiliated with, endorsed by, or
sponsored by any endpoint-management vendor.** Product and trademark names
belong to their owners. Source is publicly auditable under the MIT license.

## Reporting Vulnerabilities

Report privately via a GitHub Security Advisory on
[github.com/AIops-tools/Endpoint-AIops](https://github.com/AIops-tools/Endpoint-AIops/security/advisories)
or email zhouwei008@gmail.com. Please do not open public issues for security
reports.

## Security Design

### Credential Management
- Per-target Endpoint API keys live **encrypted** in
  `~/.endpoint-aiops/secrets.enc` (Fernet/AES-128 + scrypt-derived key; chmod
  600), never in `config.yaml` and never in source. The master password is
  never stored — only a per-store random salt and the ciphertext are on disk.
- A legacy plaintext env var `ENDPOINT_<TARGET_NAME_UPPER>_APIKEY` is still
  honoured as a fallback with a deprecation warning (migrate with
  `endpoint-aiops secret migrate`).
- The API key is sent as an `Authorization: Bearer` header at request time and
  held only in memory. Keys are never logged or echoed; the config file holds
  only host, port, api_path, and TLS settings.

### Governed Operations
Every MCP tool runs through the bundled `@governed_tool` harness
(`endpoint_aiops.governance`):
- **Audit** — every call logged to a local SQLite DB under `~/.endpoint-aiops/`
  (relocatable via `ENDPOINT_AIOPS_HOME`), agent-attributed, secret-redacted.
- **Token/runaway budget** — hard ceilings (`ENDPOINT_MAX_TOOL_CALLS` /
  `ENDPOINT_MAX_TOOL_SECONDS`) plus an on-by-default guard that trips a tight
  poll/retry loop, preventing unbounded API consumption (e.g. polling a slow
  session).
- **Risk-tier labelling** — each tool's declared `risk_level` is carried into
  the audit row as a descriptive tier. It labels the row; it does not gate the
  call. Whether a write is permitted is the agent's or the account's decision,
  not the skill's.
- **Undo-token recording** — `endpoint_assign_profile` captures the prior
  profile and records an inverse "reassign the prior profile" descriptor so the
  change can be rolled back.

### State-Changing Operations
`endpoint assign-profile` and `endpoint reboot` require double confirmation at
the CLI layer and support `--dry-run`. `endpoint_assign_profile` is
`risk_level=high` and reversible (captures the prior profile, records an undo
descriptor); `endpoint_reboot` is `risk_level=medium` and has no safe inverse
(captures the before-state for the audit record, records no undo token).

### SSL/TLS Verification
`verify_ssl` defaults to true; disable only for self-signed lab certificates.

### Prompt-Injection Protection
All server-returned text (hostnames, usernames, profile ids, session fields) is
passed through a `sanitize()` truncate + control-character strip before reaching
the agent.

### Network Scope
No webhooks, no telemetry, no outbound calls beyond the configured
endpoint-management REST API endpoint. No post-install scripts or background
services.

## Static Analysis

```bash
uvx bandit -r endpoint_aiops/ mcp_server/
uv run ruff check .
```

## Supported Versions

The latest released version receives security fixes. This is a preview (0.x);
pin a version in production.
