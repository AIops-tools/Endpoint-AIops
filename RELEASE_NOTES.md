# Endpoint AIops v0.1.0 — preview

Governed AI-ops for **managed-endpoint fleets** (thin clients / VDI) for AI
agents, with a built-in governance harness (audit, policy, token/runaway
budget, undo-token recording, graduated risk tiers) and an encrypted credential
store. Standalone — no external skill-family dependency.

> **Preview / mock-only.** All behaviour is validated against mocked REST
> responses; it has not been run against a live endpoint-management server. The
> fastest live check is `endpoint-aiops doctor`.

## Highlights

- **9 MCP tools** (7 read, 2 write), every one wrapped with `@governed_tool`.
  - Read: fleet `overview`; inventory (`endpoint_list`, `endpoint_get`);
    sessions (`session_list`, `login_storm_analysis`); drift (`drift_report`,
    `patch_status`).
  - Write: `endpoint_assign_profile` (high, reversible — records an inverse
    reassign undo), `endpoint_reboot` (medium, no safe inverse, captures
    before-state).
- **Two signature analyses** — login-storm detection + slow login/boot ranking,
  and patch/config drift vs a fleet-majority (or explicit) baseline. Both accept
  injected records for offline analysis.
- **Encrypted API key store** (`~/.endpoint-aiops/secrets.enc`, Fernet + scrypt)
  — never plaintext on disk; legacy `ENDPOINT_<TARGET>_APIKEY` env fallback.
- **CLI** with an `init` onboarding wizard, `secret` management, and `doctor`.
- **Bearer-auth REST connection layer** over a generic endpoint-management REST
  API with teaching error translation (`EndpointApiError`).

## Install

```bash
uv tool install endpoint-aiops
endpoint-aiops init
endpoint-aiops doctor
```

## Caveats

- The REST paths are modelled generically (`/endpoints`, `/sessions`,
  `/version`, `/endpoints/{id}/profile|reboot`) and need live verification.
- Out of scope by design: enrollment/de-enrollment, image/OTA management, and
  any bulk destructive operation.
