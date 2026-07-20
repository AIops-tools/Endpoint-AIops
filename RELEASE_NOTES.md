# Release notes — endpoint-aiops 0.5.0

Previous release: 0.4.0.

## In this tool

- **A real IGEL UMS dialect.** The default pointed at `/api/v2.0` on port 443; IGEL's IMI API is `/umsapi/v3` on **8443**, so both the prefix and the port were wrong and the first probe could never succeed. The generic default is no longer presented as though it targets IGEL.
- **New `scheme:`** (default `https`) — the base URL was hardcoded.

## Every tool in the line: previews and undetermined outcomes

This release fixes three harness defects that were silently degrading the audit
trail and the undo store.

**A write that loses its response is no longer recorded as a failure.** The
harness assumed a sanitized error meant nothing had happened. That assumption is
false in exactly the case that matters most: when a write severs its own
connection, the request has already landed, the response cannot come back, and
the operation was recorded as `status=error` with **no undo token created at
all**. Transport-level failures are now audited as `status=unknown`, the result
says plainly that the operation may have taken effect and should be verified
before retrying, and a write that stashed its before-state has its inverse
recorded anyway — flagged `effectVerified: false`, which `undo_list` and
`undo_apply` both surface. Existing `undo.db` files are migrated in place; their
rows read as verified, which is accurate, since the old code only ever recorded
on the confirmed path.

**A dry-run no longer writes an undo token.** Previews were recording inverses
built from a before-state they never had: the undo callback's permissive default
filled the gap with a guess, producing a real, applicable token for an operation
that never happened.

**A dry-run no longer demands a named approver.** Requiring an approval in order
to ask whether something needs approval inverts what a preview is for. The tier
is still computed and still audited, so the preview can tell you an approver
will be needed; it just no longer refuses to answer. The write itself is gated
exactly as before.

The invariant, now stated: **a dry_run may read; it must never write.** Guards
run on the preview path, which means a preview can and does report that an
operation would be refused.

## Also line-wide

- **Truncated text now ends in an ellipsis** instead of being cut silently. This
  line already treats a silent cut as a defect for lists; it was doing exactly
  that to strings.
- **Error messages are capped at 800 characters, not 300.** These messages end
  with what to do instead, so the cap was removing the most useful sentence of
  every long refusal.

## Verification status — read before relying on the IGEL preset

The dialect corrects the **paths and port**. It does **not** make this tool work
against a real IGEL UMS: IMI authenticates with HTTP Basic / a message-auth
handshake, and this tool sends a static Bearer token. That gap is unresolved and
is recorded in `docs/VERIFICATION.md`.

The preset is modelled from IGEL's published IMI documentation and is **not
verified against an appliance** — IGEL UMS has no free edition. Treat it as a
better-informed default, not as support.
