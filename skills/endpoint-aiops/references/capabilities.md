# endpoint-aiops capabilities

> Preview / mock-only. 9 MCP tools (7 read, 2 write). REST paths modelled
> generically against an endpoint-management API; need live verification.

## Read tools (7)

| Tool | REST (preview) | Returns |
|------|----------------|---------|
| `overview` | `GET /endpoints` (fold) | total, online, offline, stale[], agentVersionSpread, patchLevelSpread |
| `endpoint_list` | `GET /endpoints` | id, hostname, os, osBuild, agentVersion, patchLevel, profileId, online, lastSeenHours |
| `endpoint_get` | `GET /endpoints/{id}` | single endpoint detail (normalised) |
| `session_list` | `GET /sessions?since_hours=` | endpoint, user, loginMs, bootMs, timestamp, result |
| `login_storm_analysis` | `GET /sessions` or injected | stormCount, storms[], slowestByLogin[], slowestByBoot[], slowLoginCount, failedLogins, thresholds |
| `drift_report` | `GET /endpoints` or injected | baseline, driftByField, driftedEndpoints[], drifted/compliant counts |
| `patch_status` | `GET /endpoints` or injected | targetPatch, distribution, behind[], behindCount |

The three analysis tools accept an injected `sessions=` / `endpoints=` list for
pure/offline analysis, or pull live from a configured `target`.

## Write tools (2)

| Tool | Risk | REST (preview) | Undo / safety |
|------|------|----------------|---------------|
| `endpoint_assign_profile` | **high** | `POST /endpoints/{id}/profile` | captures the prior profile; records an inverse "reassign prior profile" undo descriptor; CLI double-confirm + dry-run |
| `endpoint_reboot` | medium | `POST /endpoints/{id}/reboot` | captures prior online state; no safe inverse, no undo; CLI double-confirm + dry-run |

## Out of scope (by design)

- Endpoint **enrollment / de-enrollment**
- Image / OTA / firmware push
- Profile CRUD (create/delete config profiles) and user/group management
- OT / industrial equipment (use the `industrial-aiops` line)

Want one of these? Open an issue or PR — feedback and contributions welcome.
