# Changelog

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
