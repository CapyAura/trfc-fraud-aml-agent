# C4 runtime metadata contract for Person B review

**Status: proposal, not yet agreed or implemented by Person B.** This contract
keeps the current evaluation JSONL schema. It does not infer labels from answer
text.

| Field | Required runtime source | Missing / not applicable behavior |
|---|---|---|
| `actual_outcome` | Emit the structured decision `answer` or `refusal` at the point where the runtime selects its final response. Keep the decision distinct from `answer` content and from the testset's expected decision. | If no decision metadata is produced, return `null`; the evaluator marks decision-dependent scoring unscorable. Never label from phrasing or answer presence. |
| `actual_refusal_type` | Emit `i` or `ii` from the runtime's structured refusal reason, only when `actual_outcome == "refusal"`. | For an answer outcome it is not applicable and remains `null`. For a refusal with no authoritative subtype, keep `null`; subtype scoring is unscorable, not incorrect. |
| `claims` | Supply explicit answer claim spans as `list[str]`. Each claim must be an exact span in `answer`; the current evaluator links it to contexts by literal matching. Do not emit claims when segmentation is unavailable. | `null` means unavailable; do not use an empty list to imply that an answer has no claims unless a completed claim extraction actually established that. Faithfulness remains unscorable when claims or contexts are unavailable. |
| `contexts` | Preserve the structured `search_policy` chunks (`doc_id` and `text`) returned by MCP. Current C code captures only valid `DOCnnnn` IDs and nonempty text. | No retrieval call means `null`; a successful retrieval returning no chunks is `[]`; malformed retrieval output is `null`. |
| `usage` | Return actual request count and provider-reported token counts only. | Unknown token counters remain `null`; they are never replaced with zero. |
| `tool_trace` | Return events for actual discovered tool calls, including step, call ID, tool name, arguments, result and status/error. | `null` means trace unavailable/incomplete and stays null even when the case outcome completed. `[]` means completed capture with no calls and is only consistent with a non-failed run. Nonempty traces may be partial after a runtime error. |
| `run_id`, timestamps | Create one opaque run ID per evaluation case and timezone-aware UTC timestamps for the case and each step event. Use the same run ID on all events for that case. | If event provenance is unavailable, do not label the record as a verified real run. Current case JSONL has a timestamp but no `run_id`; current in-memory trace events have neither. |

## Redaction before logging

The evaluation pipeline applies `eval.redaction.redact_for_log` to a copy of
each case row immediately before JSONL serialization. It recursively redacts
credential/identifier/reason fields, parses JSON-encoded tool-result strings
for nested fields, and scrubs common token formats, project account/transaction
IDs, and email addresses from free text. Runtime arguments and results remain
unchanged. Runtime errors are sanitized by the same pass before persistence.

This is best-effort filtering for the current evaluation JSONL path, not a
guarantee that arbitrary unstructured text contains no sensitive data. Any
future standalone step-event writer must call the same sanitizer before
persistence. Do not retain raw external exception bodies or customer data.

## State semantics

- `status="failed"` plus a sanitized non-null `error` records a runtime failure.
- `status="unscorable"` with null authoritative metadata records a completed
  execution whose decision cannot be evaluated.
- Case status and trace-capture status are separate: a `completed` case may have
  `tool_trace=null` if capture was unavailable/incomplete; `[]` means capture
  completed with no calls. A failed case may have a null or populated partial
  trace, but not `[]` because that would claim complete empty capture.
- A null metric is not automatically a negative result. It can mean the metric
  is not applicable (for example refusal subtype on an answer outcome) or that
  one of its required metadata fields is unavailable. The existing outcome,
  expected subtype, and actual subtype fields distinguish those cases.
- Missing `actual_outcome` makes decision scoring unscorable. Missing subtype
  makes only subtype scoring unscorable. Missing `claims` makes faithfulness
  unscorable; other independent metrics may still be scored.

## Minimal runtime interface requested

Keep `run_detailed(question)` and its existing result object. Populate
`actual_outcome`, `actual_refusal_type`, and `claims` only from explicit,
reviewable runtime metadata; keep each `None` until that source exists. Add a
case-level opaque `run_id` and timezone-aware timestamp to its result, and add
the same `run_id` plus a timestamp and redacted-logging policy to each emitted
step event. The current evaluator may continue to consume `None` values under
the existing schema; adding serialized fields requires a separate compatibility
review before changing `eval/log_validation.py` or stored JSONL.

**Current blocker:** the Groq message/runtime provides content and native tool
calls but no structured answer/refusal decision, refusal subtype, or claim
segmentation. The system prompt distinguishes two refusal reasons, but does not
emit machine-readable labels. Person B must choose and implement the explicit
decision/refusal metadata source. Person C must not infer it from generated
text.
