# C4-B2 — Runtime Outcome/Refusal Contract Investigation

**Status: proposal only; C4 remains blocked.** This report records the source-level interface and a backward-compatible contract for review. It does not claim runtime outcome/refusal metadata is currently authoritative, nor that a genuine scenario ran.

## 1. Contract currently present in source

### Runtime result

`src/trfc/agent/loop.py:33-45` defines `AgentRunResult` with `answer`, `actual_outcome`, `actual_refusal_type`, `contexts`, `claims`, `tool_trace`, `usage`, `status`, and `error`. The outcome, refusal type, and claims fields default to `None`. The adapter contract document records that the runtime initializes these fields but does not assign them (`eval/PERSON_B_C4_METADATA_CONTRACT.md:18-30`).

The orchestration's successful final-response branch stores assistant content and marks the run completed (`src/trfc/agent/loop.py:267-335`); it does not assign a structured decision or refusal classification there. Tool calls are captured in `tool_trace` with step, call ID, tool name, arguments, result, status, and error (`src/trfc/agent/loop.py:380-409`). The MCP result and tool trace alone are not an authoritative business outcome. `run_detailed()` opens an MCP stdio subprocess and returns the structured result, while `run(question) -> str` remains a compatibility wrapper (`src/trfc/agent/loop.py:425-451`).

`eval/agent_adapter.py` adapts `run_detailed()` for evaluation, and the current contract notes that missing outcome/refusal/claims values are passed through rather than derived from answer text (`eval/PERSON_B_C4_METADATA_CONTRACT.md:32-37`). `eval/run_eval.py:166-173` also accepts a structured boolean `refused` as an outcome source. That field is meaningful only if a trusted runtime supplies it; it must not be inferred from answer phrasing. The evaluator marks cases lacking a recognized outcome unscorable (`eval/run_eval.py:224-240`).

### Refusal distinctions

The system prompt distinguishes two reasons: policy information is absent from the documents, versus information exists but calculation/comparison inputs are insufficient (`prompts/system.txt:5-7`). The test/evaluation contract uses refusal subtypes `i` and `ii`; subtype correctness is separately scored only when a valid actual refusal subtype exists (`eval/run_eval.py:247-255`, `eval/README.md:41-42`). The mapping of each subtype identifier to policy semantics should be confirmed by the owners before runtime classification is added; natural-language wording is not a reliable classifier.

### Existing event formats

The existing `step_event` is a tool-call event, requiring timestamp, run/question IDs, scenario/mode, positive step, tool, args, result, and usage (`eval/log_validation.py:143-172`). `eval/step_events.py:60-105` builds these only from captured tool traces and explicitly skips unsupported refusal/no-tool cases. It must not be repurposed to represent a policy decision without a tool call.

The current working tree also contains a separate `decision_event` validator (`eval/log_validation.py:175-222`) and builder (`eval/decision_events.py:22-73`). Its shape separates outcome/refusal metadata from tool-call events and records trace availability/count and `business_outcome_verified: false`. Treat this as a Person C proposal pending cross-owner approval, not as an already agreed project contract.

## 2. Proposed additive runtime and event contract

Keep `run(question) -> str` unchanged. Continue using `run_detailed()` and add only structured fields whose source is authoritative:

| Field | Proposed type/meaning | Authoritative source and missing behavior |
|---|---|---|
| `actual_outcome` | `"answer"`, `"refusal"`, or `None` | Set at the runtime decision branch that selects the final disposition. Do not derive from answer text, test expectation, or tool-call presence. `None` means unavailable and makes decision-dependent metrics unscorable. |
| `actual_refusal_type` | `"i"`, `"ii"`, or `None` | Set only by a structured refusal-policy branch. Required when outcome is refusal for subtype scoring/event emission. On answer it is not applicable (`None`); on refusal without a classified reason it is unavailable (`None`). Confirm the i/ii semantic mapping before implementation. |
| `policy_rule_id` | Stable identifier or `None` | Optional identifier of the policy rule/decision branch that determined the result. Do not invent an ID if no such rule registry exists. |
| `decision_source` | Stable safe identifier | Required provenance for an emitted decision event (for example, a versioned policy branch identifier). It identifies the structured source, not free-form explanatory text. If unavailable, omit the decision event and report a skip reason. |
| `tool_trace` | `list[ToolEvent]` or `None` | Preserve existing semantics: `None` unavailable/incomplete, `[]` complete capture with no calls, populated list captured calls. Refusal without a tool call is represented by a decision event with complete trace and count zero only when capture actually completed. |
| `business_outcome_verified` | `false` for a decision event | A runtime decision is not proof that Freeze/Flag changed business state. Only an independent readback against the isolated database can establish that separate fact. |

### Separate decision-event record

Keep tool `step_event` unchanged. Add/retain a distinct `decision_event` record with at least:

```json
{
  "record_type": "decision_event",
  "timestamp": "timezone-aware ISO-8601 UTC",
  "run_id": "opaque run identifier",
  "question_id": "evaluation case identifier",
  "execution_mode": "real | mock | unit_test | synthetic",
  "actual_outcome": "refusal",
  "actual_refusal_type": "i",
  "policy_rule_id": "optional stable rule identifier",
  "decision_source": "stable structured source identifier",
  "tool_trace_status": "complete",
  "tool_call_count": 0,
  "business_outcome_verified": false
}
```

This is an **illustrative proposed shape, not evidence**. A no-tool refusal is a decision record, not a fabricated tool event. A refusal event is emitted only when outcome, subtype, and decision source are all structured and valid. `tool_trace_status="unavailable"` requires a null call count; a completed empty trace uses `"complete"` and `0`. `execution_mode` provenance remains a separate evaluator concern and does not itself prove a real external run.

For Freeze/Flag, the decision event must not be read as business-success evidence. Existing tool events can document that the corresponding tool call was attempted/completed, but business success requires the isolated database readback procedure and its separately retained evidence.

## 3. Ownership and responsibilities

### Person B — approval/implementation needed

Person B owns runtime, MCP/tools, and prompts per `PHAN_CONG.md:50-73` and controls the authoritative disposition decision. Before implementing, Person B should confirm:

1. Whether `run_detailed()` remains the shared runtime/evaluator interface.
2. The exact point in orchestration/policy handling that determines `answer` versus `refusal`.
3. The authoritative i/ii mapping and structured branch that emits it.
4. Whether a stable policy rule ID exists; if not, whether a versioned `decision_source` identifier is acceptable without implying a nonexistent rule catalog.
5. Whether the result dataclass can add nullable `policy_rule_id` and `decision_source` compatibly.

Likely runtime files for Person B review are `src/trfc/agent/loop.py` and, if the policy decision belongs in the prompt/policy definition, `prompts/system.txt` or the actual policy source. The precise file set depends on where the authoritative branch lives; this report does not prescribe a prompt-only classifier.

Minimum Person B tests: structured answer decision; each refusal subtype from its policy branch; ordinary answer containing refusal-like wording stays answer; missing/ambiguous policy source remains unavailable; refusal without tool calls yields no tool event; `run(question) -> str` remains compatible.

### Person C — evaluator integration after contract approval

Person C can consume the approved nullable fields in `eval/agent_adapter.py`, preserve them through `eval/run_eval.py`, validate and serialize the separate decision record in `eval/log_validation.py`/`eval/decision_events.py`, and add contract tests in `tests/`. C must not manufacture labels, rule IDs, or source provenance. The current implementation of the separate event shape is a proposal pending approval and should be reconciled with B's confirmed field names and semantics before evidence collection.

Minimum Person C tests: missing fields remain unavailable and unscorable; answer/refusal/subtype consistency is enforced; `None` and empty trace remain distinct; decision events do not become tool events; malformed source IDs are rejected; JSONL validation and append behavior remain backward compatible for existing tool events.

## 4. Decisions required before implementation

1. Confirm `run_detailed()` as the shared integration surface without changing the public string API.
2. Confirm exact subtype semantics (`i` and `ii`) against policy ownership.
3. Select the structured policy/runtime branch that is authoritative for outcome and subtype.
4. Decide the field name and whether `policy_rule_id` is available, optional, or not used; approve `decision_source` semantics.
5. Approve the additive `decision_event` schema and ensure it is versioned/compatible with existing `step_event` and case JSONL records.
6. Define which isolated readback is accepted as independent Freeze/Flag business verification; do not fold that assertion into model decision metadata.

## 5. Suggested sequence and later verification

1. Person B confirms the runtime interface, subtype mapping, and authoritative decision source.
2. Person B implements structured fields at the decision branch and adds focused runtime unit tests.
3. Person C aligns adapter serialization and event validator/builder with the approved contract; run adapter, decision-event, evaluator, and log-validation tests offline.
4. In an approved isolated environment, run the MCP subprocess against a newly created temporary SQLite database and independently read back the expected state. Do not use the default database.
5. Only after those gates, collect evaluator-generated JSONL through the approved real execution path. Preserve mode/provenance and validate schema, but do not treat schema validity alone as proof that a run was genuine.
6. Validate the three separate scenario records and their provenance; retain non-secret command/output evidence and the independent DB verification for write scenarios.

No API calls, agent runs, or database operations were performed for this contract report. It creates no JSONL evidence and does not certify runtime behavior. C4 remains blocked until the structured runtime source is agreed and supplied, business outcomes are independently verified in isolation, and the required genuine scenario evidence exists.
