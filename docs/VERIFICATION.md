# Live verification

`endpoint-aiops` is exercised by a **mock-only** test suite (`uv run pytest`, no
real management server). It has **not** yet been validated end-to-end against a
live endpoint-management server. Until it has, we do not claim it works against
a real API.

This document defines exactly what a live verification run must cover, and the
criteria for calling the tool live-verified. It is deliberately checklist-shaped
so the result is reproducible and auditable — not a subjective "seems fine".

## What the mock suite already guarantees

- Every module imports; the CLI builds; every MCP tool carries the
  `@governed_tool` harness marker (`tests/test_smoke.py`).
- The pure analyses — `login_storm_analysis` (sliding-window concurrency,
  slowest-login/boot ranking), `drift_report` / `patch_status` /
  `patch_compliance` (fleet-majority baseline derivation), and the composite
  `endpoint_health_score` — are unit-tested against synthetic session and
  endpoint records, including empty, single-record, and all-identical fleets.
- `endpoint_assign_profile` records the correct inverse undo descriptor from the
  **captured** prior profile (tested against a mocked connection);
  `endpoint_reboot` declares no undo and captures the prior online state.
- Governance persistence: audited rows actually land in the SQLite audit DB, and
  the secure-by-default approver gate refuses `high`-risk writes with no
  `rules.yaml` and no `ENDPOINT_AUDIT_APPROVED_BY`.

What it does **not** guarantee: that the REST paths (`/endpoints`, `/sessions`,
`/version`), field names, and Bearer-auth semantics match any specific
endpoint-management product. They are modelled **generically** — this is the
single largest verification gap for this tool.

## Prerequisites for a live run

A reachable endpoint-management server exposing a REST API over Bearer auth,
with at least a handful of enrolled endpoints and recent login/boot sessions
(a lab tenant or a small pilot group is enough). You need:

- An **API key with least privilege** — read on inventory/sessions, plus write
  on profile assignment and reboot for the write checks.
- A **throwaway/test endpoint** you are willing to reprofile and reboot. Never
  verify against a device someone is working on.

```bash
uv tool install endpoint-aiops
endpoint-aiops init            # encrypted secret store, TLS verify on by default
```

## Verification checklist

Tick every box. A box that cannot be ticked is a verification gap — record it,
do not silently pass.

### 1. Connectivity (the fastest live gate)
- [ ] `endpoint-aiops doctor` → all green (config, encrypted secret store, and a
      real reachability probe against the server).

### 2. Reads return real, well-shaped data
- [ ] `endpoint-aiops overview` → total/online/offline counts match the
      management console; `stale[]` lists the endpoints the console shows as not
      checked in.
- [ ] `endpoint-aiops endpoint list` → the actual enrolled endpoints, with
      populated id, hostname, online state, agent version, patch level.
- [ ] `endpoint-aiops endpoint get <id>` → one endpoint, same fields, matching
      the console for that device.
- [ ] `endpoint-aiops session list --since-hours 24` → real login/boot sessions
      with plausible timestamps and durations; no crash on missing fields.

### 3. The signature analyses hold up against real telemetry
- [ ] `endpoint-aiops session storm --since-hours 24` → during a known busy
      period, a storm episode is reported and its peak concurrency matches a
      hand count from `session list`; `slowestByLogin` / `slowestByBoot` name
      endpoints operators independently agree are slow.
- [ ] `endpoint-aiops drift report` → the derived fleet-majority baseline matches
      the real gold image, and the flagged deviating fields are genuinely
      deviating (spot-check two endpoints in the console).
- [ ] `endpoint-aiops drift patch --target-patch <level>` → the behind-target
      list matches the console's patch report.

### 4. A reversible write + its undo (governance closes the loop)
- [ ] `endpoint-aiops endpoint assign-profile <test-id> <profile> --dry-run` →
      prints the exact API call, changes nothing.
- [ ] `endpoint-aiops endpoint assign-profile <test-id> <profile>` → the console
      shows the new profile; the result carries an `_undo_id`; a row lands in
      `~/.endpoint-aiops/audit.db` tagged `high`.
- [ ] `endpoint-aiops undo list` then `endpoint-aiops undo apply <id>` → the
      **prior** profile is restored (proves undo captured pre-state, not a
      guess), and the console agrees.

### 5. An irreversible write is honest about it
- [ ] `endpoint-aiops endpoint reboot <test-id> --dry-run` → previews only.
- [ ] `endpoint-aiops endpoint reboot <test-id>` → the device actually reboots;
      the audit row is tagged `medium`, records the prior online state, and
      declares **no** undo descriptor.

### 6. Governance actually gates
- [ ] With no `~/.endpoint-aiops/rules.yaml`, `endpoint assign-profile` (high)
      is refused unless `ENDPOINT_AUDIT_APPROVED_BY` names an approver
      (secure-by-default); with it set, the approver and
      `ENDPOINT_AUDIT_RATIONALE` appear in the audit row.
- [ ] A tight poll loop trips the runaway budget guard rather than hammering the
      management API.
- [ ] Relocation works: with `ENDPOINT_AIOPS_HOME` set, `audit.db`, the undo
      store, and `secrets.enc` all land under that directory.

### 7. Cleanup
- [ ] Restore the test endpoint's original profile, confirm it is back online,
      and confirm every step above appears in the audit DB.

## Criteria to consider it live-verified

1. Every checklist box above is ticked against at least one real
   endpoint-management server, and the **product and version are recorded**
   (e.g. "verified against <product> <version>") — because the REST paths are
   generic, the specific dialect verified is the finding.
2. Any path or field-shape mismatch found during the run is fixed and covered by
   a regression test.
3. The run is written up with the date and package version, matching how the
   product line records its other live-verified tools.

## Notes for maintainers

- `endpoint-aiops doctor` is the single fastest live entry point; start there.
- The analysis tools accept **injected records**, so a partial verification is
  still valuable: export real sessions/endpoints from a server you cannot grant
  write access to, feed them to `login_storm_analysis` / `drift_report` /
  `patch_compliance` / `endpoint_health_score`, and tick sections 2 and 3 while
  leaving 4 and 5 open.
- Record the result in the product line's verification ledger once green so the
  "verification debt" list stays accurate.
