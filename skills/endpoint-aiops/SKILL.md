---
name: endpoint-aiops
description: >
  Use this skill whenever the user needs to operate a managed-endpoint fleet (thin clients, VDI endpoints, centrally-managed devices) — a one-shot fleet health overview, endpoint inventory (list/get), login & boot sessions, login-storm analysis (detect morning login storms and rank the slowest login/boot contributors), patch/config drift (which endpoints deviate from the fleet baseline), and two guarded writes (assign a config profile, reboot an endpoint).
  Always use this skill for "endpoint fleet overview", "list managed endpoints", "why is login slow this morning", "login storm", "boot time analysis", "patch drift", "config drift", "which endpoints are behind on patches", "assign a profile to an endpoint", or "reboot a thin client" when the context is an endpoint-management fleet.
  Do NOT use when the target is OT / industrial equipment (Modbus, OPC-UA, PLCs — use industrial-aiops), a hypervisor, a storage appliance, a backup product, a Kubernetes cluster, or a network device (negative routing hints only).
  Preview — common managed-endpoint operations with a built-in governance harness (audit, policy, token budget, undo, risk-tiers). Mock-validated only, not yet verified against a live management server.
installer:
  kind: uv
  package: endpoint-aiops
argument-hint: "[endpoint id or describe your fleet task]"
allowed-tools:
  - Bash
metadata: {"openclaw":{"requires":{"env":["ENDPOINT_AIOPS_CONFIG"],"bins":["endpoint-aiops"],"config":["~/.endpoint-aiops/config.yaml","~/.endpoint-aiops/secrets.enc"]},"optional":{"env":["ENDPOINT_AIOPS_MASTER_PASSWORD"]},"primaryEnv":"ENDPOINT_AIOPS_CONFIG","homepage":"https://github.com/AIops-tools/Endpoint-AIops","emoji":"💻","os":["macos","linux"]}}
compatibility: >
  Standalone, self-governed managed-endpoint operations (preview). The governance harness (audit, policy, token/runaway budget, undo, risk-tiers) is bundled in the package — no external skill-family dependency.
  All write operations are audited to a local SQLite DB under ~/.endpoint-aiops/ (relocatable via ENDPOINT_AIOPS_HOME).
  Credentials: the endpoint-management server's API key is stored ENCRYPTED in ~/.endpoint-aiops/secrets.enc (Fernet/AES-128 + scrypt-derived key) — never plaintext on disk. Run 'endpoint-aiops init' to onboard, or 'endpoint-aiops secret set <target>' to add one. The store is unlocked by a master password from ENDPOINT_AIOPS_MASTER_PASSWORD (non-interactive/MCP/CI) or an interactive prompt (CLI on a TTY). A legacy plaintext env var ENDPOINT_<TARGET_NAME_UPPER>_APIKEY is still honoured as a fallback with a deprecation warning (migrate with 'endpoint-aiops secret migrate'). The API key is sent as an Authorization: Bearer header at request time and held only in memory; keys are never logged or echoed.
  State-changing operations (assign-profile, reboot) require double confirmation at the CLI layer and support --dry-run. All write tools pass through the @governed_tool decorator (pre-check + budget guard + audit + risk-tier gate). endpoint_assign_profile is high-risk and reversible (captures the prior profile, records an inverse reassign undo descriptor); endpoint_reboot is medium-risk with no undo (a reboot has no safe inverse).
  Webhooks: none — no outbound network calls beyond the configured endpoint-management REST API.
  SSL: verify_ssl defaults to true; disable only for self-signed lab certificates.
  Transitive dependencies: httpx (HTTP client) and the MCP SDK. No post-install scripts or background services.
  PREVIEW: mock-validated only; the REST paths are modelled generically (/endpoints, /sessions, /version) and need live verification.
---

# Endpoint AIops (preview)

> **Disclaimer**: Community-maintained open-source project, **not affiliated with, endorsed by, or sponsored by any endpoint-management vendor.** Product and trademark names belong to their owners. Source at [github.com/AIops-tools/Endpoint-AIops](https://github.com/AIops-tools/Endpoint-AIops) under the MIT license.

Governed managed-endpoint operations — **9 MCP tools**, every one wrapped with the bundled `@governed_tool` harness: a local unified audit log under `~/.endpoint-aiops/`, policy engine, token/runaway budget guard, undo-token recording, and graduated-autonomy risk tiers. The management-server API key is stored **encrypted** (`~/.endpoint-aiops/secrets.enc`, Fernet + scrypt) — never plaintext on disk.

> **Standalone**: the governance harness is bundled in the package (`endpoint_aiops.governance`) — endpoint-aiops has no external skill-family dependency. **Preview / mock-only**: not yet validated against a live management server.

## What This Skill Does

| Category | Tools | Count | Read or Write |
|----------|-------|:-----:|:-------------:|
| **Overview** | fleet health overview | 1 | 1 read |
| **Inventory** | endpoint list, get | 2 | 2 read |
| **Sessions** | session list, login-storm analysis | 2 | 2 read |
| **Drift** | drift report, patch status | 2 | 2 read |
| **Remediation** | assign profile (high) | 1 | 1 write |
| | reboot (medium) | 1 | 1 write |

The analysis tools (`login_storm_analysis`, `drift_report`, `patch_status`) accept injected records for pure/offline analysis, or pull live from a configured target.

## Quick Install

```bash
uv tool install endpoint-aiops
endpoint-aiops init       # interactive wizard: connection + encrypted API key
endpoint-aiops doctor
```

## When to Use This Skill

- Triage a fleet (`overview`): online/offline counts, stale endpoints, agent/patch spread
- Diagnose a morning login storm (`session storm` / `login_storm_analysis`) and find the slowest login/boot contributors
- Find endpoints drifted from the fleet baseline (`drift report`) or behind on patches (`drift patch`)
- Assign a config profile to an endpoint (reversible) or reboot one (dry-run + double-confirm)

**Do NOT use when** the target is OT/industrial equipment (use industrial-aiops), a hypervisor, a storage appliance, a backup product, a container cluster, or a network device.

## Related Skills — Skill Routing

| If the user wants… | Use |
|--------------------|-----|
| Managed-endpoint fleet: login storms, drift, profiles | **endpoint-aiops** (this skill) |
| OT / industrial edge (Modbus, OPC-UA, PLC, PROFINET) | the **industrial-aiops** line |
| Hypervisor VM lifecycle (power, snapshot, migrate) | a hypervisor ops skill |
| Container/cluster lifecycle | a cluster ops skill |

## Common Workflows

### Diagnose a 9am login storm

1. `endpoint-aiops session storm` → storm episodes (peak concurrency, distinct users/endpoints) + the slowest logins and boots
2. Read `slowestByLogin` / `slowestByBoot` to see which endpoints/users dominate
3. Cross-check the laggards against drift: `endpoint-aiops drift report` — a stray agent version or missing patch often explains slow logins

### Bring a drifted endpoint back to baseline (reversible)

1. `endpoint-aiops drift report` → find the drifted endpoint and its deviating fields
2. `endpoint-aiops endpoint assign-profile <id> <profile> --dry-run` → preview the call
3. Re-run without `--dry-run` (double-confirm) — captures the prior profile and records an inverse reassign undo descriptor
4. If it regresses, replay the recorded undo to restore the prior profile

### Offline analysis (no live server)

Pass records straight to the analysis tools — `login_storm_analysis(sessions=[...])` or `drift_report(endpoints=[...])` — to analyse an exported dataset without connecting to a management server.

## Governance & Safety

- Every tool is audited to `~/.endpoint-aiops/audit.db` (relocatable via `ENDPOINT_AIOPS_HOME`).
- High-risk ops can require a named approver: set `ENDPOINT_AUDIT_APPROVED_BY` and `ENDPOINT_AUDIT_RATIONALE`.
- Writes support `--dry-run` and double confirmation at the CLI.
- Reversible writes record an inverse descriptor; the reboot (no safe inverse) records only the before-state.

## References

- `references/capabilities.md` — full tool + field reference
- `references/cli-reference.md` — CLI command reference
- `references/setup-guide.md` — onboarding, credentials, and connectivity
