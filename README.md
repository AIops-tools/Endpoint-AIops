<!-- mcp-name: io.github.AIops-tools/endpoint-aiops -->

# Endpoint AIops

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by any endpoint-management vendor.** Product and trademark names belong to their owners. MIT licensed.

Governed AI-ops for **managed-endpoint fleets** — thin clients, VDI endpoints,
and other centrally-managed devices — with a **built-in governance harness**:
unified audit log, token/runaway budget guard, undo-token recording, and
descriptive risk tiers. Vendor-neutral: it talks to an
endpoint-management server's REST API (Bearer auth) through a configurable
**dialect** — see [Dialects](#dialects--which-server-are-you-actually-pointing-at). Self-contained: no
dependencies beyond `httpx` and the MCP SDK. The test suite is mock-based; the
endpoint-management REST paths have not yet been exercised against a live
management server — see [`docs/VERIFICATION.md`](docs/VERIFICATION.md).

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
- **MCP server** (`endpoint-aiops mcp` or `endpoint-aiops-mcp`): **13 tools** (10 read, 3 write), every one wrapped with the bundled `@governed_tool` harness.
- **Encrypted credentials**: the management-server API key lives in an encrypted store `~/.endpoint-aiops/secrets.enc` (Fernet + scrypt) — **never plaintext on disk**. Unlock with a master password from `ENDPOINT_AIOPS_MASTER_PASSWORD` (MCP/CI) or an interactive prompt (CLI).
- **Reversibility**: `endpoint_assign_profile` (`high` risk) captures the prior profile and records an inverse "reassign the prior profile" undo descriptor. `endpoint_reboot` (`medium` risk) captures the prior online state for the audit record but declares no undo (a reboot has no safe inverse).
- **Safety**: state-changing CLI ops (`endpoint assign-profile`, `endpoint reboot`) require double confirmation and support `--dry-run`.

## Capability matrix (13 MCP tools)

| Category | Tools | Count | R/W |
|----------|-------|:-----:|:---:|
| **Overview** | `overview` | 1 | read |
| **Inventory** | `endpoint_list`, `endpoint_get`, `endpoint_health_score` | 3 | read |
| **Sessions** | `session_list`, `login_storm_analysis` | 2 | read |
| **Drift** | `drift_report`, `patch_status`, `patch_compliance` | 3 | read |
| **Remediation** | `endpoint_assign_profile` | 1 | write (high) |
| | `endpoint_reboot` | 1 | write (medium) |
| **Undo** | `undo_list` | 1 | read |
| | `undo_apply` | 1 | write (medium) |

The analysis tools (`login_storm_analysis`, `drift_report`, `patch_status`,
`patch_compliance`, `endpoint_health_score`) accept injected records for
pure/offline analysis; `endpoint_health_score` and `patch_compliance` are
injected-only, the others also pull live from a configured target.

## What this tool does, and does not, decide

It delivers managed-endpoint operations — reads and writes — accurately and
efficiently, and records every one of them. It does **not** decide whether a
write is allowed to happen. That is the agent's judgement, or the permission of
the account you connect it with: give it a management-console account or API
token scoped to a read-only role and the writes fail at the server — the place
that actually owns the permission.

So there is no read-only switch, no policy file, no approval gate to configure.
The one thing the tool guarantees is that nothing is silent: **every call, over
MCP and over the CLI alike, lands an audit row** in `~/.endpoint-aiops/audit.db`,
and reversible writes still capture their before-state and record an inverse
where one exists.

> Each tool declares a `risk_level`, kept in agreement with its `[READ]`/`[WRITE]`
> documentation tag by a test, and carried into the audit row as a descriptive
> tier — so a reviewer can see at a glance that a row was a high-risk write. It
> is a label, not a gate.

Running a smaller / local model? See
[agent-guardrails.md](skills/endpoint-aiops/references/agent-guardrails.md) — it lists
the guardrails this tool now enforces for you (so you don't spend prompt budget
restating them) and gives a ready-made system prompt for what's left.

## Payload conventions

- **Absent is not empty.** A field the management server did not report comes
  back as `null`, never as `""` — the key is always present, so a missing patch
  level cannot be mistaken for a blank one.
- **Capped lists announce themselves.** Any list a `limit` can cut short is a
  truncation envelope: `{"items": [...], "returned": N, "limit": L, "truncated":
  bool}`, with `truncated` measured rather than inferred. Companion totals
  (`driftedCount`, `behindCount`, `nonCompliantCount`, `stormCount`, the health
  `summary`) are always the full, uncapped figures.

## Quick start

### As a Claude Code plugin

One install gives an agent both the skill and the MCP server:

```
/plugin marketplace add AIops-tools/marketplace
/plugin install endpoint-aiops@aiops-tools
```

The MCP server is fetched with [uv](https://docs.astral.sh/uv/) and pinned to the
package version this plugin declares, so an audit row can be traced back to the
code that wrote it. Credentials are still configured with `endpoint-aiops init` — see below.

### As a CLI or standalone MCP server

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

Every operation — MCP **and** CLI — passes through the bundled `@governed_tool`
harness. It records; it does not authorize (see above).

- **Audit** — every call (params, result, status, duration, risk tier, and any
  operator-supplied approver/rationale) is logged to `~/.endpoint-aiops/audit.db`
  (relocatable via `ENDPOINT_AIOPS_HOME`). The CLI writes the same row the MCP
  path does — there is no unaudited entry point.
- **Runaway guard** — a safety backstop, not an authorization gate: the same
  call hammered in a tight loop trips a circuit breaker so a stuck agent can't
  burn unbounded calls/time. Disable with `ENDPOINT_RUNAWAY_MAX=0`; optional hard
  ceilings via `ENDPOINT_MAX_TOOL_CALLS` / `ENDPOINT_MAX_TOOL_SECONDS`.
- **Undo recording** — reversible writes record an inverse descriptor built from
  the fetched before-state.
- **Risk tier** — a descriptive label on the audit row derived from
  `risk_level`; it gates nothing.

## Scope

This is the **IT-endpoint** member of the AIops-tools family (governed AI-ops
with audit + budget + undo + risk tiers). For **OT / industrial edge**
(Modbus, OPC-UA, PROFINET, …) see the separate `industrial-aiops` line.

## Dialects — which server are you actually pointing at?

A **dialect** is the management server's API shape: resource paths, response
field names, the transport defaults (port + API base path), **and how to
authenticate**. Set it per target in `config.yaml`; `endpoint-aiops init` asks
for it and prints which one it configured.

| Dialect | Transport | Auth | Status |
|---------|-----------|------|--------|
| `generic` (default) | `/api/v2.0` on 443 | static Bearer API key | **Neutral placeholder — not a real vendor API.** Useful only once you describe your server's paths in a `dialect:` block. |
| `igel-ums` | `/umsapi/v3` on **8443** | HTTP Basic login → `JSESSIONID` cookie | **Documented-but-unverified dialect for IGEL UMS (IMI). This is not a claim that IGEL is supported** — see [Status](#status). |

```yaml
targets:
  - name: ums1
    host: ums.example.local
    dialect: igel-ums        # IMI paths, port 8443, /umsapi/v3, Basic-login auth
    username: ums-admin      # UMS account; the password lives in secrets.enc
    scheme: https            # or 'http' for a reverse-proxied server
    verify_ssl: false        # self-signed lab UMS only
```

The `generic` default is **not** an IGEL configuration and never was: IGEL
serves IMI at `/umsapi/v3` on 8443, so a target left on the generic shape 404s
on its first probe. That mismatch is why the preset exists.

Where a server genuinely has no such resource, the dialect says so rather than
guessing a URL — IMI exposes no login/boot session resource, so `session_list`
and `login_storm_analysis` on an `igel-ums` target return a teaching error
naming the absent resource instead of calling an invented path.

A dialect selects the **auth scheme** too, not just paths — IMI rejects the
static Bearer token the generic dialect sends, so it logs in with HTTP Basic at
`POST /umsapi/v3/login` and carries the returned `JSESSIONID` cookie (once per
connection, then cached). Because the scheme comes from the dialect, a
credentials failure and a *wrong-dialect* failure are reported differently: a
401 names the scheme presented and, when the server sends a `WWW-Authenticate`
challenge, the scheme it actually wants — so a dialect mismatch does not send
you off rotating a perfectly good key.

⚠️ Note for IGEL specifically: a UMS account with too few permissions receives
**empty lists rather than a 403**. `endpoint-aiops doctor` authenticates as a
step separate from its reachability probe and warns when a successful login
returns no endpoints, because "no devices" and "not allowed to see the devices"
are otherwise indistinguishable.

## Status

The test suite is mock-based. **No dialect in this package has been exercised
against a real management server**, so this package does not claim support for
any specific product — including IGEL.

- `generic` is a **placeholder shape**, not a vendor API.
- `igel-ums` is a **documented-but-unverified dialect**. Its paths and field
  aliases are modelled from IGEL's published IMI documentation; its auth scheme
  is documented in the IMI manual and matches what three independent real-world
  IMI clients do. Neither has been run against an appliance by this project —
  IGEL UMS has no free edition, so it cannot be verified on the maintainer's
  hardware.

Both are recorded as UNKNOWN-pending-live in
[`docs/VERIFICATION.md`](docs/VERIFICATION.md), which ranks what a live run is
most likely to find wrong and defines the checklist it must cover. If you have a
UMS and run that checklist, the results are very welcome as an issue. Missing a
capability or a server dialect? Open an issue or PR — contributions welcome.
