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
- Governance persistence: audited rows actually land in the SQLite audit DB. The
  harness authorizes nothing — there is no read-only, deny-rule, or approver gate
  to test.

What it does **not** guarantee: that the REST paths, field names, or the
authentication scheme match any specific endpoint-management product. The auth
strategies are unit-tested for *shape* (Basic login, cookie reuse, one handshake
per connection) against a mocked transport — which proves the code does what it
was told to do, not that any server agrees. This is the single largest
verification gap for this tool.

## Dialect verification status

| Dialect | Transport | Status |
|---------|-----------|--------|
| `generic` | `/api/v2.0` on 443 | **Placeholder, not a real vendor API.** Nothing serves this shape out of the box; it is a starting point for a hand-written `dialect:` block. |
| `igel-ums` | `/umsapi/v3` on 8443 | **UNKNOWN — pending live.** |

### `igel-ums` is modelled from documentation, NOT verified

The IGEL preset — **resource paths, field aliases, port, API base path, and
authentication** — is derived from IGEL's published IGEL Management Interface
(IMI) documentation. **None of it has been run against a real IGEL UMS.** IGEL
UMS has no free edition, so it cannot be verified on the maintainer's hardware —
this is an access limitation, not a decision to skip the work. Status is
**UNKNOWN — pending live**, not "correct".

The auth scheme is on a firmer footing than the paths, and it is worth being
precise about the difference rather than flattening both into "unverified":

- **Paths and field aliases** — read off the documentation, nothing else.
- **Auth (`imi-session`)** — documented in IGEL's IMI manual *and* corroborated
  by three independent real-world clients (IGEL Community's PSIGEL
  `New-UMSAPICookie`, the community curl HOWTO, ControlUp's UMS script), which
  all perform the same Basic-login → `JSESSIONID`-cookie flow.

That is still **not** live verification: this project has never executed it
against an appliance. "Documented and corroborated by other people's working
code" is a stronger claim than "doc-modelled" and a weaker one than "verified".

#### What a live run must prove, most-likely-wrong first

1. **Auth actually completes** — `POST /umsapi/v3/login` with Basic returns a
   body carrying `message`, and the resulting `Cookie: JSESSIONID=…` is accepted
   on the next call. The single most likely failure is the **session id's exact
   shape**: IMI's documented `message` value is `"JSESSIONID=<hex>"`, i.e. a
   complete `name=value` pair, not a bare id. `_session_cookie` handles both, but
   only a live run proves which one a given UMS build sends.
2. **`profile_path` and `reboot_path`** — both **write** paths, so a wrong guess
   is the most expensive to discover in production. Verify with `--dry-run`
   first, then against a throwaway device.
3. **Permissions vs. emptiness** — an account without at least Read/Browse at
   the Devices level gets an **empty list, not a 403**. Confirm the endpoint
   count against the UMS console. An empty list here proves nothing on its own;
   `doctor` now warns about exactly this, and the warning must not be dismissed.
4. **`list_key`** — assumed `None` (IMI returns a bare array). If IMI wraps its
   lists in an envelope, every list read returns empty — and per (3) that failure
   is camouflaged.
5. **Session expiry** — IMI sessions last 30 minutes on a *sliding* window. A
   long-lived connection that idles past it should see a 401 naming the scheme;
   confirm a reconnect recovers cleanly.
6. **Field aliases** (`unitID`, `unitName`, `firmwareVersion`, …) — a miss
   degrades to `null` fields rather than an error, so it will not announce itself.

#### Asserted, not guessed — keep it that way

- **IMI exposes no login/boot session resource**, so `sessions_path` is `None`
  and the session tools raise `UnsupportedResource` naming the absent resource.
  If a live run finds IMI *does* expose one, that is a finding — add the path
  rather than assuming the tools were broken.
- **IMI does not accept a static Bearer token.** The `igel-ums` dialect
  therefore selects the `imi-session` strategy; it is not a Bearer dialect with
  different paths. No gateway or adapter is required any more — but see (1)
  above before treating the login as known-good.
- **`/serverstatus` is IMI's only unauthenticated endpoint.** `doctor` uses it
  for the reachability hop and then authenticates *separately*, so a green
  reachability tick can never stand in for an auth check that never ran.

> Why this section is worded so cautiously: the previous default silently
> presented `/api/v2.0` on 443 as though it targeted IGEL. It targeted nothing —
> the first probe would 404 — and the mock suite was green because the fixtures
> asserted the same invented shape the code called. Doc-modelled paths are a
> weaker claim than mock-tested ones, not a stronger one.

## Prerequisites for a live run

A reachable endpoint-management server whose dialect this package can speak,
with at least a handful of enrolled endpoints and recent login/boot sessions
(a lab tenant or a small pilot group is enough). You need:

- **Credentials with least privilege** — read on inventory/sessions, plus write
  on profile assignment and reboot for the write checks. The shape depends on
  the dialect: `generic` takes an API key; `igel-ums` takes a UMS administrator
  **username + password** (set `username:` on the target, password in the
  encrypted store) with at least Read/Browse at the Devices level.
- A **throwaway/test endpoint** you are willing to reprofile and reboot. Never
  verify against a device someone is working on.

```bash
uv tool install endpoint-aiops
endpoint-aiops init            # encrypted secret store, TLS verify on by default
```

## Verification checklist

Tick every box. A box that cannot be ticked is a verification gap — record it,
do not silently pass.

### 1. Connectivity and authentication (the fastest live gate)
- [ ] `endpoint-aiops doctor` → all green (config, encrypted secret store, a
      real reachability probe, **and a separate authentication check**).
- [ ] The doctor line naming the auth scheme matches what the product actually
      wants. On a mismatch the 401 says so explicitly — that is a dialect
      problem, not a credentials problem, and rotating the key will not fix it.
- [ ] `doctor` did **not** print the "authenticated but returned no endpoints"
      warning. If it did, resolve it before ticking anything below: on IGEL UMS
      that is what insufficient Devices-level permission looks like, and every
      subsequent read would be silently empty.

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

### 6. Audit is unbypassable — both entry points
- [ ] Run a `high`-risk op (`endpoint assign-profile`) over MCP and the same op
      over the CLI; confirm **both** land a row in `audit.db`, and that
      `ENDPOINT_AUDIT_APPROVED_BY` / `ENDPOINT_AUDIT_RATIONALE`, when set, appear
      on the row (recorded, never required — the skill authorizes nothing).
- [ ] A tight poll loop trips the runaway budget guard rather than hammering the
      management API.
- [ ] Relocation works: with `ENDPOINT_AIOPS_HOME` set, `audit.db`, the undo
      store, and `secrets.enc` all land under that directory.

### 7. Cleanup
- [ ] Restore the test endpoint's original profile, confirm it is back online,
      and confirm every step above appears in the audit DB.

## Criteria to consider it live-verified

1. Every checklist box above is ticked against at least one real
   endpoint-management server, and the **product, version and dialect are
   recorded** (e.g. "verified against <product> <version> via dialect X") —
   because the REST paths are dialect-specific, *which dialect was verified* is
   the finding. Ticking this list against `generic` verifies nothing about
   `igel-ums`, and vice versa: the table in "Dialect verification status" is
   per-row, and a row only moves off UNKNOWN when that dialect was the one
   exercised.
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
