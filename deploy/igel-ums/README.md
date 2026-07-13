# `deploy/igel-ums/` — endpoint-aiops against an IGEL UMS (overlay)

> **One distribution target, not the core.** endpoint-aiops stays **vendor-neutral**
> — it speaks a generic endpoint-management REST shape. This folder is a thin
> **overlay** that points it at a specific management server via a *dialect* (a
> paths + field-name mapping). No vendor names live in the installable package.
> **Status: preview / `待核实`.**

## What a dialect is

endpoint-aiops normalises whatever a management server returns into one stable
shape (`id`, `hostname`, `online`, `agentVersion`, `patchLevel`, …). Servers
differ in **resource paths** and **field names**; a `dialect:` block on a target
in `config.yaml` describes those, so the same tools (`overview`, `endpoint_list`,
`drift_report`, `endpoint_health_score`, …) work unchanged. The built-in default
is the generic shape; this overlay supplies an **IGEL UMS (IMI)** mapping.

## Use

Merge the `dialect:` block from [`dialect.yaml`](dialect.yaml) into your target in
`~/.endpoint-aiops/config.yaml`, then run as usual:

```bash
endpoint-aiops doctor
endpoint-aiops overview
endpoint-aiops endpoint list
```

The tools now hit the IMI paths (`/umsapi/v3/thinclients`, …) and map IMI fields
into the normalised model — no code change.

## Caveats (`待核实`)

- **Paths / field names** vary by UMS + IMI version — confirm each against the IMI
  API docs for your UMS. The values in `dialect.yaml` are a starting map, not verified
  against a live UMS.
- **Auth**: IMI uses HTTP Basic / a message-auth handshake, **not** a static Bearer
  token. The dialect maps only paths + fields; a live integration also needs an auth
  adapter (future) or a gateway that presents Bearer to endpoint-aiops. This is why
  the mapping ships as an overlay, not as a built-in dialect.
- Everything here is **read-first**; the two write tools (assign-profile, reboot) map
  to IMI command endpoints (`待核实`) and stay governed (dry-run + double-confirm).

Missing a field or a path? PRs welcome — but keep vendor-specific mappings in
`deploy/`, never in the neutral package.
