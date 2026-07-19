# endpoint-aiops setup & security guide

> Not yet exercised against a live endpoint-management server (see docs/VERIFICATION.md).

## 1. Install

```bash
uv tool install endpoint-aiops
```

## 2. Create a management-server API key

In your endpoint-management server's web UI, create an API key (usually under a
Credentials / API Keys section). Copy the key. endpoint-aiops sends it as
`Authorization: Bearer <key>` against the REST API base
`https://<host>:<port><api_path>`.

## 3. Onboard

```bash
endpoint-aiops init
```

The wizard collects (non-secret) connection details into
`~/.endpoint-aiops/config.yaml` and stores the API key **encrypted** into
`~/.endpoint-aiops/secrets.enc`. Example config:

```yaml
targets:
  - name: ums1
    host: 10.0.0.30
    port: 443
    verify_ssl: false          # self-signed lab certs only
    api_path: /api/v2.0
```

## 4. Non-interactive use (MCP server / CI / cron)

Export the master password so the encrypted store can be unlocked without a
prompt:

```bash
export ENDPOINT_AIOPS_MASTER_PASSWORD='your-master-password'
```

## Credential security

- The API key is **never** written to disk in plaintext. It lives only in
  `~/.endpoint-aiops/secrets.enc`, encrypted with Fernet (AES-128-CBC + HMAC),
  the key derived from your master password via scrypt. Only a per-store random
  salt and the ciphertext are on disk (chmod 600); the master password itself is
  never stored.
- A legacy plaintext env var `ENDPOINT_<TARGET_NAME_UPPER>_APIKEY` is still
  honoured as a fallback with a deprecation warning — migrate with
  `endpoint-aiops secret migrate` (it imports then renames the old `.env`).
- The key is held only in memory during a session and is never logged or echoed;
  exception text and tracebacks are scrubbed of secret-shaped strings before
  being written to the audit log.

## Governance harness state

State lives under `~/.endpoint-aiops/` (relocate with `ENDPOINT_AIOPS_HOME`):

- `audit.db` — every tool call (SQLite), with risk tier, approver, rationale
- `rules.yaml` — policy: deny rules, maintenance windows, approval tiers
- `undo.db` — inverse descriptors for reversible writes (e.g. `endpoint_assign_profile`)
- budget / runaway guard — caps cumulative tool calls and wall-time; trips on
  tight poll/retry loops

## Verify

```bash
endpoint-aiops doctor
```

`doctor` checks the config file, the encrypted store and its permissions,
that an API key is present per target, and (unless `--skip-auth`) connectivity
by hitting `/version`.
