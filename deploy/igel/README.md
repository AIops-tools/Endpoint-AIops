# `deploy/igel/` — endpoint-aiops in an IGEL fleet (overlay)

> **One distribution target, not the core.** endpoint-aiops stays **vendor-neutral**.
> This folder is a thin **IGEL overlay** describing where it fits and how to run it
> against an IGEL fleet — no vendor names live in the installable package.
> **Status: preview / `待核实`.**

## Where endpoint-aiops sits — the management plane (read this first)

endpoint-aiops is **not** an on-endpoint app. It runs on the **management plane**:
one instance, near the **UMS**, that reads the fleet (inventory, sessions, patch/
config state) and — governed — nudges it (assign profile, reboot). It does **not**
run on each thin client.

That is the deliberate split from the OT-line sibling, **iaiops**:

| | Runs where | What it does | IGEL packaging |
|---|---|---|---|
| **iaiops** (OT) | **on the endpoint** | governed, read-first OT diagnostics of the field the device connects to | an **App Portal app** — see the [community recipe](https://github.com/IGEL-Community/IGEL-OS-APP-RECIPES/pull/520) |
| **endpoint-aiops** (IT) | **management plane** (by the UMS) | manages the IGEL fleet itself — health, login storms, patch/config drift | a **container on a management host**, *not* an App Portal endpoint app |

Together they cover both layers: OT diagnostics **on** the device, fleet
management **of** the devices. They are two separate products, co-deployed — not
one merged tool.

## Why it is *not* an App Portal recipe

App Portal / Managed-Container recipes deploy an app **onto a thin client**.
endpoint-aiops is a management-side workload, so it is **not** submitted as an App
Portal endpoint app. Its IGEL angle is instead:

1. **UMS/IMI integration** — point it at a UMS via the config *dialect* in
   [`../igel-ums/`](../igel-ums/) (resource paths + field mapping). *Preview: IMI
   auth is still on the to-do list — the dialect maps paths + fields today.*
2. **IGEL Ready / ecosystem** — a management-tool integration (not an endpoint
   app), the natural home for a fleet-management workload.

## Run it (management host / Managed-Container infra)

Use the neutral OCI image ([`../Dockerfile`](../Dockerfile)) on any container host
that can reach the UMS. The MCP server speaks **stdio** (the MCP client launches
it), so run it attached, with the fleet state persisted:

```bash
# build the neutral image (or pull yours)
docker build -t <registry>/endpoint-aiops:0.1.0 -f deploy/Dockerfile .

# 1) point it at the UMS: merge deploy/igel-ums/dialect.yaml into the target in
#    /state/config.yaml (mounted as ENDPOINT_AIOPS_HOME), then:
podman run --rm -v endpoint-state:/state <registry>/endpoint-aiops:0.1.0 endpoint-aiops doctor
podman run --rm -v endpoint-state:/state <registry>/endpoint-aiops:0.1.0 endpoint-aiops overview

# 2) as an MCP server (client attaches over stdio):
podman run -i --rm -v endpoint-state:/state <registry>/endpoint-aiops:0.1.0 endpoint-aiops mcp
```

Read-first + governed: every tool runs through the audit / budget / risk-tier /
undo harness; the two writes (assign-profile, reboot) are off by default
(dry-run + double-confirm).

## Caveats (`待核实`)

- Not validated against a live UMS; IMI paths/fields (`../igel-ums/dialect.yaml`)
  and **IMI auth** need confirming — the dialect maps paths + fields, not auth yet.
- The MCP transport is stdio (no always-on network endpoint), so endpoint-aiops is
  typically run on-demand by the MCP client / operator rather than as a daemon.
