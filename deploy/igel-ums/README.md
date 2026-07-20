# `deploy/igel-ums/` — endpoint-aiops against an IGEL UMS (overlay)

> **Superseded by a shipped preset.** `igel-ums` is now a built-in dialect: put
> `dialect: igel-ums` on the target in `~/.endpoint-aiops/config.yaml` (or pick
> it in `endpoint-aiops init`) and you get the IMI paths, port 8443 and base
> path `/umsapi/v3` without copying anything from here. Keep using this overlay
> only if your UMS differs from the preset and you need to override parts of it —
> a `dialect:` block may name `preset: igel-ums` and state just the delta.
>
> **Status: `待核实` — modelled from IGEL's IMI documentation, NOT live-verified.**
> See [`docs/VERIFICATION.md`](../../docs/VERIFICATION.md), where this is
> recorded as UNKNOWN-pending-live.

## What a dialect is

endpoint-aiops normalises whatever a management server returns into one stable
shape (`id`, `hostname`, `online`, `agentVersion`, `patchLevel`, …). Servers
differ in **resource paths** and **field names**; a `dialect:` block on a target
in `config.yaml` describes those, so the same tools (`overview`, `endpoint_list`,
`drift_report`, `endpoint_health_score`, …) work unchanged. The built-in default
is a neutral **placeholder** that no real server serves; the shipped `igel-ums`
preset supplies an **IGEL UMS (IMI)** mapping, and this overlay shows the same
mapping in longhand for anyone who needs to adjust it.

## Use

Simplest path — name the shipped preset:

```yaml
targets:
  - name: ums1
    host: ums.example.local
    dialect: igel-ums
```

To override part of it, merge the `dialect:` block from
[`dialect.yaml`](dialect.yaml) into your target in `~/.endpoint-aiops/config.yaml`
(add `preset: igel-ums` to keep the rest of the preset), then run as usual:

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
