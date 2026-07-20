<!-- mcp-name: io.github.AIops-tools/endpoint-aiops -->

# Endpoint AIops

> **Disclaimer**: Community-maintained open-source project. **Not affiliated with, endorsed by, or sponsored by any endpoint-management vendor.** Product and trademark names belong to their owners. MIT licensed.

Governed AI-ops for **managed-endpoint fleets** — thin clients, VDI endpoints,
and other centrally-managed devices — with a **built-in governance harness**:
unified audit log, policy engine, token/runaway budget guard, undo-token
recording, and graduated-autonomy risk tiers. Vendor-neutral: it talks to an
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

## Security: read-only mode

This tool is meant to be handed to an AI agent, so its safety story is enforced
by the server rather than requested in a prompt:

```bash
export ENDPOINT_READ_ONLY=1
```

With that set, the **3 write tools are never registered**. An MCP client
lists **10 tools instead of 13** — the writes are not hidden, not
gated behind a flag, and not merely refused when called. They are absent from
the session. A model cannot invoke a tool it was never offered, and cannot be
argued into one.

That distinction is the whole point. A tool that exists but refuses still invites
retry loops and "I'll describe the call instead" behaviour from smaller models,
and it leaves a reviewer trusting a promise. An absent tool is a fact you can
check: connect, list the tools, and see that the writes are not there.

Enforcement is two layers deep, so the switch cannot be sidestepped by changing
entry point:

| Layer | What it does | Covers |
|---|---|---|
| `@governed_tool` harness | refuses every non-read operation outright | MCP, CLI, and in-process callers |
| MCP registration | write tools are removed from `list_tools()` | anything speaking MCP |

Read operations are unaffected, and every call is still audited to
`~/.endpoint-aiops/audit.db`.

> The read/write split is derived from each tool's declared `risk_level`, and a
> test asserts that this never disagrees with the `[READ]`/`[WRITE]` tag in the
> tool's own documentation — so a write can't quietly present itself as a read.

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

## Dialects — which server are you actually pointing at?

A **dialect** is the management server's API shape: resource paths, response
field names, and the transport defaults (port + API base path). Set it per
target in `config.yaml`; `endpoint-aiops init` now asks for it and prints which
one it configured.

| Dialect | Transport | Status |
|---------|-----------|--------|
| `generic` (default) | `/api/v2.0` on 443 | **Neutral placeholder — not a real vendor API.** Useful only once you describe your server's paths in a `dialect:` block. |
| `igel-ums` | `/umsapi/v3` on **8443** | IGEL UMS via the IGEL Management Interface (IMI). **Modelled from IGEL's published IMI documentation — NOT live-verified.** |

```yaml
targets:
  - name: ums1
    host: ums.example.local
    dialect: igel-ums        # sets IMI paths, port 8443, base path /umsapi/v3
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

⚠️ **IMI auth**: IGEL's IMI uses HTTP Basic / a message-auth handshake, not the
static Bearer token this tool sends. A live IGEL integration also needs an auth
adapter or a gateway that presents Bearer. The dialect maps paths and fields
only.

## Status

The test suite is mock-based. **No dialect in this package has been exercised
against a real management server.** The `generic` shape is a placeholder, and
the `igel-ums` preset is modelled from vendor documentation — recorded as
UNKNOWN-pending-live in [`docs/VERIFICATION.md`](docs/VERIFICATION.md), which
defines the checklist a live run must cover. IGEL UMS has no free edition, so it
cannot be verified on the maintainer's hardware. Missing a capability or a server
dialect? Open an issue or PR — contributions welcome.
