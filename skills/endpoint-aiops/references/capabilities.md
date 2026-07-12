# endpoint-aiops capabilities

> Preview / mock-only. 11 MCP tools (9 read, 2 write). REST paths modelled
> generically against an endpoint-management API; need live verification.

## Read tools (9)

| Tool | REST (preview) | Returns |
|------|----------------|---------|
| `overview` | `GET /endpoints` (fold) | total, online, offline, stale[], agentVersionSpread, patchLevelSpread |
| `endpoint_list` | `GET /endpoints` | id, hostname, os, osBuild, agentVersion, patchLevel, profileId, online, lastSeenHours |
| `endpoint_get` | `GET /endpoints/{id}` | single endpoint detail (normalised) |
| `endpoint_health_score` | injected only | endpointsEvaluated, baseline{agentVersion,patchLevel,source}, summary{healthy,degraded,critical}, worst[]{endpoint,score,band,reasons[]}, note |
| `session_list` | `GET /sessions?since_hours=` | endpoint, user, loginMs, bootMs, timestamp, result |
| `login_storm_analysis` | `GET /sessions` or injected | stormCount, storms[], slowestByLogin[], slowestByBoot[], slowLoginCount, failedLogins, thresholds |
| `drift_report` | `GET /endpoints` or injected | baseline, driftByField, driftedEndpoints[], drifted/compliant counts |
| `patch_status` | `GET /endpoints` or injected | targetPatch, distribution, behind[], behindCount |
| `patch_compliance` | injected only | endpointsEvaluated, targetPatch, targetSource, slaTargetPct, complianceRatePct, compliantCount, verdict, nonCompliant[], note |

The analysis tools accept an injected `sessions=` / `endpoints=` list for
pure/offline analysis. `login_storm_analysis`, `drift_report` and `patch_status`
also pull live from a configured `target`; `endpoint_health_score` and
`patch_compliance` are injected-only (they score rows you already hold, e.g.
from `endpoint_list`).

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
