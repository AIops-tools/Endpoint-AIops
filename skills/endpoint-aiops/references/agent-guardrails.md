# Agent guardrails — running endpoint-aiops with a smaller / local model

If you drive these tools with a local model (Llama, Qwen, Mistral … via Goose,
Ollama, LM Studio, or any OpenAI-compatible runtime), you will get noticeably
better results with a short system prompt. This page gives you one, and — more
importantly — tells you which guardrails you **no longer need to write**, because
the tool now enforces them itself.

The distinction matters. A guardrail in a prompt is a request. A guardrail in the
harness is a guarantee. Anything below that we could move into the harness, we did.

## What the tool now enforces — do not waste prompt budget on these

| You might be tempted to prompt | Why you don't need to |
|---|---|
| "Work read-only, never change an endpoint" | Set `ENDPOINT_READ_ONLY=1`. The write tools (`endpoint_assign_profile`, `endpoint_reboot`, `undo_apply`) are then **not registered at all** — they never appear in the tool list, so the model cannot call one even if it tries. The `@governed_tool` harness independently refuses writes, so the CLI is covered too. |
| "Don't invent a value when a field is missing" | A field the management server did not return comes back as `null`, never as `""`. An endpoint with no reported `patchLevel` is distinguishable from one reporting a blank level, and the key is always present. |
| "Tell me if the output was cut off" | Every capped list is `{"items": [...], "returned": N, "limit": L, "truncated": true/false}`. Truncation is measured against the full result, not guessed from the row count matching the limit. |
| "Give me the real totals, not just what you can see" | Counts are computed over the whole fleet, never over the capped list: `driftedCount`, `behindCount`, `nonCompliantCount`, `stormCount`, and the health-score `summary` are all uncapped. `complianceRatePct` is likewise a whole-fleet figure. |
| "Explain why something was flagged" | Every flag carries its number: each health-score deduction is cited in that endpoint's `reasons`, each drift row states `expected` vs `actual`, and `login_storm_analysis` returns the `thresholds` it used. |
| "Confirm before anything destructive" | `endpoint assign-profile` and `endpoint reboot` require `--dry-run`-able preview + double confirmation at the CLI, and a named approver (`ENDPOINT_AUDIT_APPROVED_BY`) for high-risk tiers. |
| "Log what you did" | Every MCP call is audited to `~/.endpoint-aiops/audit.db` regardless of what the model says it did. |
| "Remember the previous profile so we can roll back" | `endpoint_assign_profile` reads the endpoint's current profile *before* changing it and records an inverse undo token — the before-state is captured, never guessed. (A reboot has no safe inverse and honestly declares none.) |

## What still needs a prompt

These are model-behaviour problems the harness cannot fix from the outside.
Copy this into your agent's system prompt:

```text
You operate a managed-endpoint fleet (thin clients / VDI / managed devices)
through the endpoint-aiops MCP tools.

TOOL USE
- Before answering any question about the current fleet, you MUST call a tool.
  Never answer from memory or assumption.
- Actually invoke the tool. Do not describe the call you would make, and do not
  emit an example JSON response in place of calling it.
- If a tool call fails, report the real error verbatim. Never fill the gap with
  a plausible-sounding answer.

READING RESULTS
- Read the whole result before concluding. A list arrives as
  {"items": [...], "returned": N, "limit": L, "truncated": bool}; when
  "truncated" is true, say so and re-run with a higher limit instead of
  treating the partial list as the whole fleet.
- Use the uncapped counts (driftedCount, behindCount, nonCompliantCount,
  stormCount, summary) for "how many", and the items list only for "which ones".
- A null field means the management server did not report that value. Report it
  as "not available" — never infer a patch level, agent version, or hostname.
- Report values exactly as returned. Do not normalise, translate, or prettify
  patch levels, agent versions, profile ids, or hostnames.
- A health score is advisory: it is 100 minus the deductions listed in that
  endpoint's "reasons". Quote the reasons rather than restating the score alone.

SCOPE
- Separate observation from interpretation. State what the tools returned, then
  any interpretation, clearly marked as such.
- Do not assert a login-storm, drift, or patch-compliance problem unless a tool
  result supports it — a storm is only a storm when an episode was returned.
- A drift finding is an exact string mismatch against a baseline, and that
  baseline may be the fleet majority rather than a declared gold image. Say
  which (the payload tells you: baselineSource / targetSource).
- Do not confuse an endpoint id with a hostname, or a profile id with either.
- Do not add generic advice that does not follow from the tool output.
```

## Recommended setup for a local model

```bash
# Read-only until you trust the setup — this is enforced, not advisory.
export ENDPOINT_READ_ONLY=1
endpoint-aiops doctor
```

Then, when you are ready to allow writes, unset it and set an approver so the
high-risk tier has an accountable name on it:

```bash
unset ENDPOINT_READ_ONLY
export ENDPOINT_AUDIT_APPROVED_BY="your.name@example.com"
export ENDPOINT_AUDIT_RATIONALE="scheduled patch window 2026-07-20"
```

## If your model still struggles

Some behaviours are model-capacity limits rather than prompt problems:

- **Multi-tool workflows time out or drift.** Prefer the analysis tools —
  `overview`, `login_storm_analysis`, `drift_report`, `endpoint_health_score`
  each do the multi-step correlation inside one call, so the model does not have
  to chain reads and keep endpoint ids straight.
- **The model ignores later tool results in a long context.** Ask narrower
  questions and use `--limit` deliberately rather than pulling a whole fleet
  inventory into the context window.
- **The model describes calls instead of making them.** This is usually a
  runtime/tool-calling-format mismatch, not a prompt problem — check that your
  client advertises the tools in the format your model was trained on.

Feedback on running this with a specific local model is genuinely useful —
open an issue at
[github.com/AIops-tools/Endpoint-AIops](https://github.com/AIops-tools/Endpoint-AIops/issues)
with the model, runtime, and what went wrong.
