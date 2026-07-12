<!-- mcp-name: io.github.AIops-tools/endpoint-aiops -->

# Endpoint AIops (preview)

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by any endpoint-management vendor.** Product and trademark names belong to their owners. MIT licensed.

Governed AI-ops for **managed-endpoint fleets** — thin clients, VDI endpoints,
and other centrally-managed devices — with a **built-in governance harness**:
unified audit log, policy engine, token/runaway budget guard, undo-token
recording, and graduated-autonomy risk tiers. Vendor-neutral: it talks to an
endpoint-management server's REST API (Bearer auth). Self-contained: no
dependencies beyond `httpx` and the MCP SDK. **Preview — mock-validated only,
not yet verified against a live management server.**

## What it does

Two signature analyses, plus the guarded reads and writes around them:

- **Login-storm analysis** — during a "everyone logs in at 9am" incident,
  detect the storm (bursts of concurrent logins in a sliding window) and rank
  the endpoints/users dragging login and boot times. Every flag is reported
  with its number, not a black-box verdict.
- **Patch / config drift** — find endpoints that have drifted from the fleet
  (outdated patch level, stray agent version, divergent OS build or config
  profile). With no declared baseline it derives one by fleet majority, so it
  works before a gold image exists.

## What works

- **CLI** (`endpoint-aiops ...`): `init`, `overview`, `endpoint list/get/assign-profile/reboot`, `session list/storm`, `drift report/patch`, `secret set/list/rm/migrate/rotate-password`, `doctor`, `mcp`.
- **MCP server** (`endpoint-aiops mcp` or `endpoint-aiops-mcp`): **11 tools** (9 read, 2 write), every one wrapped with the bundled `@governed_tool` harness.
- **Encrypted credentials**: the management-server API key lives in an encrypted store `~/.endpoint-aiops/secrets.enc` (Fernet + scrypt) — **never plaintext on disk**. Unlock with a master password from `ENDPOINT_AIOPS_MASTER_PASSWORD` (MCP/CI) or an interactive prompt (CLI).
- **Reversibility**: `endpoint_assign_profile` (`high` risk) captures the prior profile and records an inverse "reassign the prior profile" undo descriptor. `endpoint_reboot` (`medium` risk) captures the prior online state for the audit record but declares no undo (a reboot has no safe inverse).
- **Safety**: state-changing CLI ops (`endpoint assign-profile`, `endpoint reboot`) require double confirmation and support `--dry-run`.

## Capability matrix (11 MCP tools)

| Category | Tools | Count | R/W |
|----------|-------|:-----:|:---:|
| **Overview** | `overview` | 1 | read |
| **Inventory** | `endpoint_list`, `endpoint_get`, `endpoint_health_score` | 3 | read |
| **Sessions** | `session_list`, `login_storm_analysis` | 2 | read |
| **Drift** | `drift_report`, `patch_status`, `patch_compliance` | 3 | read |
| **Remediation** | `endpoint_assign_profile` | 1 | write (high) |
| | `endpoint_reboot` | 1 | write (medium) |

The analysis tools (`login_storm_analysis`, `drift_report`, `patch_status`,
`patch_compliance`, `endpoint_health_score`) accept injected records for
pure/offline analysis; `endpoint_health_score` and `patch_compliance` are
injected-only, the others also pull live from a configured target.

## Quick start

```bash
uv tool install endpoint-aiops          # or: pipx install endpoint-aiops
endpoint-aiops init                     # wizard: add a target + store its API key (encrypted)
endpoint-aiops doctor                   # verify config, secrets, connectivity
endpoint-aiops overview                 # one-shot fleet health
endpoint-aiops session storm            # detect a login storm + slow contributors
endpoint-aiops drift report             # endpoints drifted from the fleet baseline
```

Run as an MCP server (stdio):

```bash
export ENDPOINT_AIOPS_MASTER_PASSWORD=...   # unlock secrets non-interactively
endpoint-aiops-mcp
```

## Governance

Every MCP tool passes through the bundled `@governed_tool` harness:

- **Audit** — every call (params, result, status, duration, risk tier,
  approver, rationale) is logged to `~/.endpoint-aiops/audit.db` (relocatable
  via `ENDPOINT_AIOPS_HOME`).
- **Budget / runaway guard** — token and call budgets trip a circuit breaker.
- **Risk tiers** — graduated autonomy; high-risk ops can require a named
  approver (`ENDPOINT_AUDIT_APPROVED_BY` / `ENDPOINT_AUDIT_RATIONALE`).
- **Undo recording** — reversible writes record an inverse descriptor.

## Scope

This is the **IT-endpoint** member of the AIops-tools family (governed AI-ops
with audit + budget + undo + risk tiers). For **OT / industrial edge**
(Modbus, OPC-UA, PROFINET, …) see the separate `industrial-aiops` line.

## Status

**Preview — mock-validated only.** The endpoint-management REST paths are
modelled generically (`/endpoints`, `/sessions`, `/version`) and need live
verification against a real server. Missing a capability or a server dialect?
Open an issue or PR — contributions welcome.
