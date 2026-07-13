# Changelog

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
