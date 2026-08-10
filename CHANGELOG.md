# Changelog

## v0.9.0 — 2026-08-10

### Fixed
- **The CLI reported a refused or failed governed write as a success.** 3 write call sites printed the governed twin's payload and exited **0** whatever it said — and `@tool_errors` flattens every refusal, guard rejection and upstream failure into `{"error": ...}` rather than raising, so nothing downstream of a `&&` chain or a CI step could tell a blocked write from a landed one. The dry-run path already exited non-zero, which made the asymmetry worse: the preview was stricter than the write it previews. Results now route through a `checked()` helper — exit 1 on an error payload, exit 2 on an undetermined outcome, unchanged on success. This defect class had been fixed repo-by-repo several times and kept coming back; an audit across the whole line found it live in **18 of the 24 tools at once (87 call sites)**, so each tool now carries an invariant test that fails if any future CLI command prints a governed result without checking it.

## v0.8.0 — 2026-08-03

### Fixed
- **`undo apply` replays against the target the original write ran on.** It dispatched the inverse against whatever target the *caller* named — in practice the config's first entry — while the write's own target sat unused in the undo record. On a multi-target config the inverse therefore ran against the wrong host; it only looks harmless because the resource usually is not there, but two hosts holding the same name and the inverse **succeeds on the wrong one, silently**. An explicitly named target still wins. Line-wide: all 24 copies had the identical defect. Caught live in container-host-aiops, where a stop recorded against a Podman target replayed against a Portainer one.

## v0.7.0 — 2026-08-02

### Changed (BREAKING)
- **Requires MCP SDK 2.0** (`mcp[cli]>=2.0,<3.0`). `mcp.server.fastmcp` no longer exists in 2.0; the server is now built with `MCPServer` and reports its package version in the stdio handshake.

### Fixed
- **`undo apply` works from the CLI.** Every write tool is imported lazily inside its own CLI command, so a CLI-driven undo ran in a process where the inverse tool was never registered and failed with "inverse tool is not registered" — for every write tool. Only the MCP entry point, which imports the whole server, worked. Found while live-verifying against a real cluster.
- **An undetermined outcome is audited `unknown`, not `ok`.** The harness only classified a result as undetermined when the payload *also* carried an `error` key, so a write that looked successful but had not been confirmed was recorded as a success.


## v0.6.0 — 2026-07-21

### Changed (BREAKING)
- **Removed the authorization layer** — read-only mode, the approver gate, and rules.yaml deny are gone. The skill no longer decides read vs write; that is the agent's judgement or the connecting account's permissions. `<PREFIX>_READ_ONLY` now has no effect (a startup warning is logged); `<PREFIX>_AUDIT_APPROVED_BY`/`_RATIONALE` are optional audit annotations.
- The retained guarantee is **unbypassable audit over MCP and CLI alike** — no unaudited entry point. Harness = audit + runaway safety guard + undo + sanitize; `risk_level` is a descriptive audit label, not a gate.

See RELEASE_NOTES.md for tool-specific changes.


## v0.5.0 — 2026-07-20

### Fixed
- **A real IGEL UMS dialect.** The default pointed at `/api/v2.0` on port 443; IGEL's IMI API is `/umsapi/v3` on **8443**, so both the prefix and the port were wrong and the first probe could never succeed.
- **New `scheme:`** (default `https`) — the base URL was hardcoded..
- Harness: a write whose response is lost is audited `status=unknown`, not `error` — it may have taken effect. Undo tokens gain `effectVerified` (undo.db migrated in place).
- Harness: a dry-run no longer records an undo token, and no longer requires a named approver. Guards now run on the preview path.
- Truncated strings end in an ellipsis instead of being cut silently; error messages are capped at 800 chars, not 300.

See RELEASE_NOTES.md for the full detail.

## v0.3.0 — 2026-07-17

### Added
- **Undo executor**: `undo list` / `undo apply <id>` (CLI + MCP) — apply a recorded replayable inverse; the dispatched inverse is re-gated by its own risk tier; single-use, dry-run, double-confirm, both wrapper + inverse audited.

## v0.2.1 — 2026-07-16

### Fixed
- **`secrets.enc` now follows `ENDPOINT_AIOPS_HOME`** (secretstore hardcoded the real
  home directory; config/audit/undo already relocated — found in live verification).
- **Audit fidelity**: failures sanitized into `{"error": ...}` results by the MCP error
  layer are now audited as `status=error` (they previously read as `ok`, hiding failed
  attempts from exception reports), and no undo is recorded for a call that failed.

### Tests
- `doctor` and the `init` wizard are now fully covered (previously ~10–20%); plus a
  regression test for the sanitized-failure audit status.

## v0.2.0 — 2026-07-13

Security-hardening release from a line-wide code review.

### Changed (behavior)
- **Secure by default**: with no `rules.yaml`, high/critical operations now require a
  named approver (`ENDPOINT_AUDIT_APPROVED_BY`). A fresh install no longer allows
  destructive writes unattended; `init` seeds a starter `rules.yaml` you can edit,
  and an operator-authored rules file is honoured as-is.
- `__version__` is now single-sourced from package metadata (the previous release
  self-reported a stale version string).
- Sanitize docs no longer overstate scope: it strips control/format characters and
  truncates; semantic prompt-injection resistance must come from the consuming agent.

### Fixed
- Agent-supplied ids are percent-encoded in management-API URL paths (path-traversal hardening).
- `init` TLS verification prompt now defaults to ON.
- CHANGELOG cleanup (stray Unreleased section merged into v0.1.1).

### Tests
- Governance persistence is now tested against REAL `audit.db`/`undo.db` files
  (write → audit row + inverse undo row with captured prior state).
- The CLI confirmed-write path (dry-run / double-confirm / governed execution) is
  covered end-to-end.
- `pytest-cov` added to the dev dependencies.

## v0.1.1

- Fix: `ENDPOINT_AIOPS_HOME` now also relocates `config.yaml` (was hardcoded to `~/.endpoint-aiops`).
- Fix: **CLI writes are now audited + undo-recorded** via the governance path — previously only the MCP tools recorded audit/undo; CLI `manage`/`remediate`/etc. writes now go through the same `@governed_tool` layer (they keep their dry-run + double-confirm). CLI write output is now the governed JSON result. No API/tool changes.

### Added

- **Deploy overlays** — a neutral OCI image (`deploy/Dockerfile`) and an IGEL
  deployment note (`deploy/igel/README.md`) placing endpoint-aiops on the
  **management plane** (a container by the UMS, *not* an on-endpoint App Portal
  app) alongside the `deploy/igel-ums/` dialect. Vendor names stay in `deploy/`;
  the package remains vendor-neutral.
- **Management-server dialects** — a per-target `dialect:` block in `config.yaml`
  describes a server's **resource paths** and **response field aliases**, so the
  same tools adapt to a differently-shaped endpoint-management API with no code
  change. The built-in generic dialect reproduces the previous behaviour exactly;
  vendor-specific mappings ship as `deploy/` overlays, keeping the package
  vendor-neutral. (`endpoint_aiops/dialect.py`.)
- **`endpoint_health_score`** (read, low) — a composite per-endpoint health/risk
  score (0-100). Pure analysis over injected inventory rows: it folds the fleet
  signals already known (offline, stale, patch-behind, agent-behind) into one
  ranked "which endpoints are worst?" view, deducting points per risk signal and
  citing every deduction in the endpoint's `reasons`. Baseline is provided or
  derived by fleet majority; scores map to bands (healthy ≥80, degraded 50-79,
  critical <50). Brings the MCP tool count to **10** (8 read, 2 write).
- **`patch_compliance`** (read, low) — the SLA/compliance companion to
  `patch_status`. Pure analysis over injected inventory rows: instead of the
  patch-level distribution it reports what fraction of the fleet is on the target
  patch level (exact-match on `patchLevel`, fleet-majority derived when no target
  is given), whether that meets the SLA (`meets_sla` / `below_sla` /
  `insufficient` for an empty fleet), and which endpoints are non-compliant.
  Advisory only. Brings the MCP tool count to **11** (9 read, 2 write).

All notable changes to endpoint-aiops are documented here. This project adheres
to [Semantic Versioning](https://semver.org/).

## [0.1.0] — preview

Initial preview release: governed AI-ops for managed-endpoint fleets (thin
clients / VDI) with a bundled governance harness. **Mock-validated only — not
yet verified against a live endpoint-management server.**

### Added

- **9 MCP tools** (7 read, 2 write), every one wrapped with the bundled
  `@governed_tool` harness (audit, policy, token/runaway budget, undo,
  risk-tiers):
  - **Overview** — `overview` (fleet health: online/offline, stale endpoints,
    agent/patch spread).
  - **Inventory** — `endpoint_list`, `endpoint_get`.
  - **Sessions** — `session_list`; `login_storm_analysis` — detect login storms
    (bursts of concurrent logins in a sliding window) and rank the slowest
    login/boot contributors.
  - **Drift** — `drift_report` (endpoints deviating from a per-field baseline,
    fleet-majority derived when none is given); `patch_status` (patch-level
    distribution + endpoints behind the target).
  - **Remediation** — `endpoint_assign_profile` (write, high, reversible:
    captures the prior profile, records an inverse reassign undo descriptor);
    `endpoint_reboot` (write, medium, no safe inverse, captures before-state).
- **Pure/offline analysis** — `login_storm_analysis`, `drift_report`, and
  `patch_status` accept injected records for analysis without a live server.
- **Encrypted secret store** — the management-server API key is stored encrypted
  in `~/.endpoint-aiops/secrets.enc` (Fernet + scrypt); never plaintext on disk.
  Legacy `ENDPOINT_<TARGET>_APIKEY` env var honoured as a fallback.
- **CLI** (`endpoint-aiops`) — `init` wizard, `secret` management, `doctor`,
  `overview`, and the `endpoint` / `session` / `drift` sub-commands.
- **Bearer-auth REST connection layer** over a generic endpoint-management REST
  API with centralised teaching error translation (`EndpointApiError`).

### Known limitations

- Preview / mock-only: the REST paths (`/endpoints`, `/sessions`, `/version`,
  `/endpoints/{id}/profile`, `/endpoints/{id}/reboot`) are modelled generically
  and need live verification against a real management server.
- Out of scope by design: enrollment/de-enrollment, image/OTA management, and
  any bulk destructive operation.
