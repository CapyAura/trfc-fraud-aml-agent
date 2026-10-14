# C4 runtime metadata contract for Person B review

**Status:** Person B approved the contract. Person C's adapter consumes the
existing source-level `AgentRunResult` interface for fields it actually
supplies. This keeps `run(question) -> str` and the current evaluation JSONL
schema unchanged. Production LLM-agent policy metadata remains unavailable unless produced by an
authoritative runtime branch. A separate deterministic offline policy contract
now covers only the explicitly sourced, documented branches described below;
its provenance is synthetic.

## Current runtime API observed in source

`src/trfc/agent/loop.py` currently exposes both `async run(question: str) ->
str` and `async run_detailed(question: str, *, model_request=...) ->
AgentRunResult`. The public `run` awaits the detailed call and returns the
answer string on completion or `Error: {error}` on failure. It therefore loses
all structured fields and a legitimate answer beginning with `Error: ` is
ambiguous to a string-only adapter.

`AgentRunResult` is a dataclass with these fields and defaults:

| Field | Source behavior verified in `loop.py` |
|---|---|
| `answer: str \| None` | Final assistant content on successful completion; can remain null on errors. |
| `actual_outcome: str \| None` | Initialized to null and never assigned by current runtime. |
| `actual_refusal_type: str \| None` | Initialized to null and never assigned by current runtime. |
| `contexts: list[str] \| None` | Collected only from valid serialized `search_policy` chunks containing a valid document ID and nonempty text. Null when no captured retrieval or capture is malformed; an empty list can represent valid retrieval with no chunks. |
| `claims: list[str] \| None` | Initialized to null and never assigned by current runtime. |
| `tool_trace: list[dict[str, Any]] \| None` | Set to `[]` after tool discovery; populated with captured calls. A failed run with no events is changed to null; partial events remain on failure. MCP setup failure returns null. |
| `usage: dict[str, int \| None] \| None` | Aggregated actual request count and provider counters. Null if there are no counted requests; unknown provider counters remain null. |
| `status: str` | Defaults to `failed`; set to `completed` only on a valid final answer. Error returns retain `failed`. |
| `error: str \| None` | Set on caught runtime/model/tool/connection errors; otherwise null. |

The source describes this as a provisional detailed result. The built-in
adapter uses it once per case, validates its runtime type and status, passes
through its fields, and preserves null trace/usage/metadata and partial results
on structured failures. This does not change the public string API. Person B
should be notified of the adapter integration and coordinate before changing
the dataclass. No adapter may derive labels or claims from answer text.

## Runtime/evaluator options for Person B review

| Option | Effect | Assessment |
|---|---|---|
| A. Keep evaluator on `run(question) -> str` | Retains the public API and avoids internal coupling, but usage, contexts, trace, status, and errors are lost. Prefix matching `Error: ` is ambiguous. Outcome-dependent cases remain unscorable. | Backward-compatible but materially less useful and cannot faithfully represent runtime failures. |
| B. Have the evaluator call existing `run_detailed()` once | Keeps `run(question) -> str` unchanged and passes through the dataclass fields already produced by the runtime. Captures contexts, usage, trace lifecycle, partial trace and explicit status/error where available. | **Selected as the minimal source-supported adapter behavior.** It does not supply authoritative outcome, refusal subtype, or claims; those remain null. Coordinate with Person B before runtime changes. |
| C. Define a new shared result contract | Requires a new/versioned interface and coordinated runtime/evaluator changes. | Use only if Person B does not want `run_detailed()` treated as the integration point or needs a different stable contract. |

Option B is selected for Person C's adapter based on the existing source. This
selection does not claim live integration has been verified or that the
runtime's missing metadata has been implemented.

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

## Production runtime metadata integration notes

The evaluator already consumes the current `run_detailed(question)` result.
If runtime metadata is added, keep that result interface and its public
`run(question) -> str` wrapper backward-compatible, or explicitly
version/document another API. Populate
`actual_outcome`, `actual_refusal_type`, and `claims` only from explicit,
reviewable runtime metadata; keep each `None` until that source exists. Add a
case-level opaque `run_id` and timezone-aware timestamp to its result, and add
the same `run_id` plus a timestamp and redacted-logging policy to each emitted
step event. The current evaluator may continue to consume `None` values under
the existing schema; adding serialized fields requires a separate compatibility
review before changing `eval/log_validation.py` or stored JSONL.

**Production blocker:** the Groq message/runtime provides content and native
tool calls but no structured policy decision, refusal subtype, or claim
segmentation. The system prompt does not emit machine-readable labels. The
offline contract below does not resolve production LLM metadata provenance.

## C4-FINAL-7 explicit offline contract

`src/trfc/agent/policy.py` defines `StructuredPolicyRequest` and
`PolicyDecision`. Malformed shapes/values raise `TypeError`/`ValueError`; valid
but insufficient facts yield `status="needs_information"` with null outcome,
subtype, rule ID, and source. The contract validates relevant typed fields and
non-empty references but does not authenticate caller-supplied references or
facts; it therefore does not emit decisions from those inputs.

DOC0009 Arts. 3–5 define the closed supported-method list and DOC0007 Art. 12
defines missing-history handling; these documents define policy, not the
transaction facts supplied in `StructuredPolicyRequest`. Because no
authenticated method classification or transaction-log completeness source is
integrated, even recognized values return `needs_information` with null outcome,
subtype, rule ID, and decision source. `claims` remain null because there is no
verified claim-span producer. Freeze/Flag requests remain needs-information
because no authenticated controller approval or structured matched-rule source
exists. Cross-intent context fields are rejected as contradictory.

`trfc.agent.offline.run_policy_offline()` converts the deterministic decision
into `AgentRunResult`. `eval.agent_adapter:offline_policy_case` passes only
`policy_request` into that entry point and is fixed to `synthetic` provenance.
The normal Groq-backed `run_case` and public `run(question) -> str` behavior are
unchanged. Caller-supplied evidence references are not authenticated by this
offline API; consequently its output is contract/test evidence, not genuine
production scenario evidence. It performs no DB, MCP, LLM, or API operation.
