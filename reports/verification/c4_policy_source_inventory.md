# C4 policy-source inventory

**Purpose:** identify business rules that are actually documented, where the
runtime could apply them, and which structured evaluation metadata can be
truthfully emitted today. This inventory is source review, not proof that the
runtime executed a decision.

## Documented rules and runtime readiness

| Rule supported by source | Authoritative source | Runtime decision point / current capability | Metadata available truthfully |
|---|---|---|---|
| An out-of-scope payment method must be refused as “not in the documents”; unlisted methods must not default to a supported method. | `data/docs/DOC0009.md`, Arts. 1–5 (closed list and out-of-scope handling); `DE_TAI_TRFC_Agent.md` §2 (refusal kind i). | No structured payment-method field is accepted by `run_with_session()` (`src/trfc/agent/loop.py:269`) or a dedicated scope tool. It receives a free-form question and model tool calls. `Transaction.method` is returned by `get_transactions()` (`src/trfc/tools/impl.py:25`) but is a database row, not an authoritative classification of the user’s question. There is no safe deterministic refusal branch to attach here. | No outcome, subtype, rule ID, or decision source. Retrieved chunks may be captured as contexts when returned by `search_policy` (`loop.py:247`, `391`). |
| Missing source logs/data must not be treated as normal; inability to evaluate must remain distinct from a negative finding. | `data/docs/DOC0001.md` Art. 3; `DOC0004.md` Arts. 3, 12; `DOC0006.md` Arts. 7, 12; `DOC0007.md` Art. 12; `DE_TAI_TRFC_Agent.md` §2 (refusal kind ii). | `get_transactions()` returns a list or an error string (`impl.py:25`); it carries no completeness, retention, or synchronization status. An empty list cannot establish that logs are complete and empty. The loop records returned tool data but does not make a completeness decision (`loop.py:390–404`). | No refusal/outcome subtype or decision source. Actual tool result and status can remain in `tool_trace`; token usage is only provider reported. |
| Risk rules include daily limit excess, geographic impossibility, transaction splitting, behavioral deviation, and watchlist matches; missing required inputs mean “not evaluated,” not “normal.” | `data/docs/DOC0004.md`, Arts. 3–12. | No rule-evaluation service is called by the runtime. `Transaction` has amount/time/country/method/location (`src/trfc/tools/schemas.py:28`) but no completeness status or account tier. `get_transactions()` does not expose tier or rule hits. The watchlist itself is explicitly outside DOC0004. `DOC0007.md` supplies limits, but tier is not returned by the current transaction tool. | No risk outcome or claim can be attributed to a concrete rule execution. Contexts and captured tool calls remain available when valid. |
| Limit calculation uses current eKYC tier and complete transactions; a limit breach rejects the transaction and creates an alert, but does not automatically freeze the account. | `data/docs/DOC0007.md`, Arts. 4–12; `data/docs/DOC0008.md`, Arts. 2–4; `data/docs/DOC0001.md`, Arts. 5, 12. | `accounts.ekyc_tier` exists in SQLite (`src/trfc/tools/state.py:25–29`) but `get_transactions()` does not return it; no alert/limit decision tool exposes a structured decision. The LLM currently chooses tool calls. | No authoritative limit outcome, refusal, or rule ID from the runtime. A tool acknowledgement is not the business decision. |
| Only a controller may decide to freeze; an alert needs original transaction ID and excess ratio before a freeze decision. | `data/docs/DOC0008.md`, Arts. 3–6, 12; `DOC0007.md` Art. 11. | Runtime has no authenticated actor/role, alert record, controller approval, or typed excess-ratio input. `freeze_account_temporarily(account_id, reason)` accepts a free-form reason (`src/trfc/tools/impl.py:121`) and the agent dispatches model-selected tools (`loop.py:369–405`). Enforcing an “allowed controller” branch without a trusted identity/approval source would be unsafe; silently denying all callers would also change existing behavior without an implementable authorization contract. | No authorization decision metadata. The isolated-DB write guard is a separate technical safety check (`src/trfc/tools/state.py:85`), not controller authorization or a refusal classification. |
| Risk evaluation can create a suspicious-transaction flag; the tool writes a flag record. | `data/docs/DOC0001.md` Arts. 11–12; `data/docs/DOC0004.md` Arts. 2, 9, 11; `data/docs/DOC0008.md` Arts. 4, 9; implementation `src/trfc/tools/impl.py:152`. | `flag_suspicious_tx(tx_id, reason)` mutates the transaction and inserts a `flags` row, but it receives no structured matched-rule list and does not produce a policy decision object. A successful write is not evidence that a documented detection rule was matched. | Tool trace is available; actual matched rule, outcome metadata, and claims are not. Independent DB readback can verify the side effect but not establish why policy selected it. |
| Policy citations and factual claims must be supported by returned source material; expected evaluation labels describe tests, not runtime decisions. | `prompts/system.txt` rules 1–3; `DE_TAI_TRFC_Agent.md` §§2, 7; `tests/testset.jsonl` contains expected labels only. | `_retrieved_contexts()` captures valid returned chunks (`src/trfc/agent/loop.py:247`); no runtime component emits claim spans or links them to contexts. Final answer content is assigned at `loop.py:335–337`, without structured decision fields. | `contexts` can be populated from actual retrieved chunks. `claims` remains unavailable; do not derive it from answer text or expected labels. |

## Existing structured transport

`AgentRunResult` declares nullable outcome, refusal type, policy rule ID,
decision source, contexts, claims, trace, usage, status, and error
(`src/trfc/agent/loop.py:34–47`). `run_with_session()` captures actual
retrieval contexts, tool calls, and provider usage. Its final-answer branch
currently sets only `answer`, `status`, and usage (`loop.py:335–337`); it does
not create an outcome/refusal/claims decision.

The registered adapter passes through fields returned by `run_detailed()`
(`eval/agent_adapter.py:47–69`). `evaluate()` copies those fields and emits a
decision event only when the runtime provided acceptable structured metadata
(`eval/run_eval.py:222–227, 328–336`; `eval/decision_events.py:22–72`). The
decision-event schema requires a refusal subtype of `i` or `ii`
(`eval/log_validation.py:175–211`). Thus fake integration tests can verify this
transport, but cannot supply the missing runtime source.

## Field-by-field conclusion

| Field | Current truthful source | Status |
|---|---|---|
| `actual_outcome` | No structured policy decision branch; final text is not a decision signal. | **Unavailable** |
| `actual_refusal_type` | Design documents define i/ii examples, but runtime does not execute typed refusal branches. | **Unavailable** |
| `policy_rule_id` | Document article references exist; no runtime rule registry or executed rule ID exists. | **Unavailable** |
| `decision_source` | No structured decision producer. Prompt wording and final text are not authoritative. | **Unavailable** |
| `claims` | No claim segmentation or claim-to-context evidence producer. | **Unavailable** |
| `contexts` | Valid chunks actually returned from `search_policy`. | **Available when captured; otherwise null** |
| `tool_trace` | Discovered MCP calls and results captured by the loop. | **Available when capture completes; null when unavailable** |
| `usage` | Request counts and provider-reported counters. | **Available only to the extent returned; missing counters stay null** |
| Freeze/Flag business effect | Independent readback from isolated SQLite can verify state mutation. | **User reports verifier passed; this does not identify a policy decision/rule** |

## Missing interfaces before a runtime policy decision can be authoritative

1. A structured, validated payment method/scope fact (not extracted from a
   natural-language question) and its source, for an out-of-scope decision.
2. A completeness/synchronization signal for transaction logs and required
   fields, so missing data can be distinguished from an empty result.
3. The account tier and rule-match outputs needed by DOC0004/DOC0007, including
   watchlist information if that rule is claimed.
4. An authenticated controller identity and a verifiable written approval
   record before a freeze can be authorized under DOC0008. A free-form
   `reason` argument does not establish authorization.
5. A structured claim representation with provenance links to actual answer
   spans and retrieved evidence, if claims are required for faithfulness.

Until those sources exist, adding a policy classifier at the agent boundary
would require inferring facts from user prose, LLM prose, expected test labels,
or unverified tool acknowledgements. No such classifier or metadata assignment
was added. The existing adapter/event transport remains usable once a genuine
runtime decision source is implemented.

## C4-FINAL-7 implementation, superseded by C4-FINAL-8

C4-FINAL-7 introduced the typed `StructuredPolicyRequest` and separate offline
adapter. The subsequent C4-FINAL-8 provenance audit found that its nonempty
caller-provided `evidence_ref` and typed facts were not authenticated. The
policy path was changed: those inputs no longer produce outcome, subtype, rule
ID, or decision-source metadata. The offline evaluator now records
`needs_information` and emits no decision event. It still does not execute
Freeze/Flag, access a database, or call the LLM/MCP agent.

## C4-FINAL-8 input provenance audit

| Input / metadata | Type and current source | Trust/completeness/freshness | Validation and fail-closed behavior | Can authorize action? |
|---|---|---|---|---|
| `intent` | String supplied by the offline caller. | Configuration choice only; not policy evidence. | Restricted to four recognized intent strings; unknown values raise `ValueError`. Cross-intent fields raise `ValueError`. | No. Freeze/Flag intents return `needs_information`. |
| `payment_method_code` | Optional string supplied by caller. DOC0009 Arts. 3–5 define PM01–PM04 and describe out-of-scope categories; no current adapter maps an authoritative transaction/request to these inputs. Native transaction rows use `method`, but no verified mapping from those values to this contract is implemented. | Caller-supplied and unauthenticated; no source identity, observation time, or completeness marker. | Unknown values return `needs_information`; known code plus any reference still returns `payment_method_provenance_unverified`. Malformed/irrelevant fields are rejected. | No. |
| `transaction_log_status` | Optional enum-like string supplied by caller. DOC0007 Art. 12 and DOC0006 Art. 12 describe deletion and synchronization handling. `get_transactions()` returns transaction rows or an error string; it does not report retention/completeness status. | Caller-supplied, unauthenticated, and not tied to a verified query/snapshot. No observation timestamp. | Unknown enum values raise `ValueError`; all recognized statuses with a caller reference return `transaction_log_provenance_unverified`. | No. |
| `evidence_ref` | Optional non-empty string supplied by caller. No source registry/provider validates it. | Presence is checked; authenticity, scope, freshness, and relation to the other fields are not verifiable. A non-empty string is not proof. | Missing reference returns `source_evidence_reference_unavailable`; arbitrary references do not unlock decisions. | No. |
| Operator identity / freeze approval | No corresponding runtime/request field or authenticated identity/approval service. `freeze_account_temporarily(account_id, reason)` accepts a free-form reason only. | Unavailable; cannot assess validity, revocation, freshness, or contradiction. | Extra approval fields are rejected by the offline adapter; freeze and flag remain needs-information. | No. |
| Rule match / rule ID | No policy rule evaluator or executed match is returned by agent/tool dispatch. DOC article identifiers are policy-source citations, not runtime matches. | No runtime match evidence. | No `policy_rule_id` or `decision_source` is assigned. | No. |
| Claims / source evidence | Runtime may capture retrieved contexts from actual `search_policy` results; there is no claim-span extractor/linker. Offline policy path performs no retrieval. | Claims unavailable; caller answer and expected labels are not sources. | `claims=None`; no faithfulness claim is emitted. | No. |

Freshness cannot be validated because the current request has no authenticated
observation timestamp/version source; a caller-supplied timestamp is rejected
as an unsupported field. No current structured input can trigger a real
refusal event or business action. The offline evaluator can only record the
case as unscorable with `policy_decision_status="needs_information"`.

## C4-FINAL-9 continuation — policy source classification and field audit

### 1. Five-tier source authority classification

| Tier | Category | Component / Field | Description and current state |
|---|---|---|---|
| **Tier 1** | **Authoritative source exists and has been verified** | `contexts` (retrieval output from `search_policy`) | Verifiable when `search_policy` chunks match regex `DOC\d{4}` and contain non-empty text (`src/trfc/agent/loop.py:250-268`). **Limitation:** Capturing a chunk text with a regex-matched `DOC0004` reference proves only that the text was retrieved from the policy corpus; it does *not* prove that a risk rule engine executed, or that the chunk's content is an authoritative ruling on the case. |
| | | `tool_trace` (captured MCP execution) | Verifiable when MCP tool discovery and calls complete during runtime loop (`src/trfc/agent/loop.py:342-409`). **Limitation:** Capturing MCP tool calls in `tool_trace` proves that the client dispatched and recorded tool execution; it does *not* prove that a protected write action (Freeze/Flag) succeeded in changing business state or was independently read back from the database. |
| | | `usage` (provider metrics) | Verifiable to the extent reported by model collaborator (`src/trfc/agent/loop.py:52-99`). Unknown counters remain `None`. **Limitation:** Provider token usage counters prove provider accounting only; they do *not* prove that the generated output is policy-compliant or authoritative. |
| **Tier 2** | **Implementation or schema exists; authority not established** | `StructuredPolicyRequest` & `PolicyDecision` | Typed contracts implemented with exact type checks and frozen slots in `src/trfc/agent/policy.py`. Upstream producers supplying authenticated facts do not exist. |
| | | `decision_event` schema & builder | Implemented and validated in `eval/log_validation.py` and `eval/decision_events.py`. Built-in agent runtime lacks structured policy decision branches to populate it truthfully. |
| | | `policy_decision_status` & `policy_reason_code` | Transported across `AgentRunResult` and evaluation case rows; captures `needs_information` and reason codes. |
| **Tier 3** | **Source is absent** | Payment-method classifier | No upstream component evaluates questions or transactions against DOC0009 Art. 3 closed list. |
| | | Log completeness / synchronization provider | `get_transactions()` in SQLite tool returns rows/errors; no signal exists for log retention expiration (DOC0006/0007 Art. 12) or sync state. |
| | | Operator approval & controller identity | No role authentication or written approval record exists in runtime or tool interfaces (DOC0008). |
| | | Executed risk rule-matching engine | No rule evaluator exists to match transaction features against DOC0004 rules. |
| | | Claim segmentation & provenance linker | No component extracts claims from answer text or links them to retrieved document spans for faithfulness. |
| **Tier 4** | **Source is inaccessible or cannot be verified safely** | Production database (`data/state.db`) | Access, modification, seeding, or reset is strictly prohibited by safety policies. |
| | | Live Groq API / external LLM | Live calls prohibited; agent orchestration cannot be exercised live in this verification turn. |
| | | Live Freeze / Flag operations on business targets | Prohibited without verified controller identity and approved isolated test targets. |
| **Tier 5** | **Data is synthetic / test-only** | `offline_policy_case` | Adapter immutably registered with `mode="synthetic"`, provider `"offline-policy-v1"` (`eval/agent_adapter.py:99-101`). |
| | | Injected test adapters (`build_adapter`) | Permitted only for `mock`, `unit_test`, or `synthetic` modes (`eval/agent_adapter.py:104-118`). |
| | | Pytest fixtures | Isolated temporary databases and fake model responses across `tests/`. Cannot be presented as authentic business evidence. |

### 2. Comprehensive field-by-field provenance and decision-sufficiency matrix

| Field | Intended meaning | Source of truth | Producer & consumer | Authentication & integrity expectations | Completeness & synchronization expectations | Relevant code & tests | Sufficient for final decision? |
|---|---|---|---|---|---|---|---|
| `intent` | Caller objective: payment method scope, log assessment, freeze, flag | Caller configuration | Producer: offline caller / test case. Consumer: `evaluate_structured_request`. | Must be string in allowlisted set. Cannot smuggle cross-intent context. | N/A (configuration intent). | `src/trfc/agent/policy.py:58-61`; `tests/test_offline_policy.py:84-100`. | **No** (intent declaration is not evidence). |
| `evidence_ref` | Pointer to supporting source record | External source registry / audit log | Producer: caller. Consumer: `evaluate_structured_request`. | Must be non-empty string. Note: **A reference is only a pointer; it does not prove existence, authenticity, or content.** | Must point to an immutable, synchronized log entry. | `src/trfc/agent/policy.py:62-66, 78-79, 91-92`; `tests/test_offline_policy.py:26-44`. | **No** (unauthenticated reference yields `needs_information`). |
| `payment_method_code` | Transaction payment method classification | Core banking / payment gateway | Producer: absent. Consumer: `evaluate_structured_request`. | Cryptographic or trusted signature confirming method classification against DOC0009. | Complete transaction capture without fallback to PM01. | `src/trfc/agent/policy.py:72-83`; `tests/test_offline_policy.py:26-44`. | **No** (no authenticated producer; yields `payment_method_provenance_unverified`). |
| `transaction_log_status` | Status of transaction logs: complete, deleted_after_retention, sync_error, unknown | Database engine / log archival system | Producer: absent. Consumer: `evaluate_structured_request`. | Signed archive audit record confirming log lifecycle per DOC0006/DOC0007. | Must distinguish complete empty period from log deletion or sync partition. | `src/trfc/agent/policy.py:84-96`; `tests/test_offline_policy.py:46-63`. | **No** (no authenticated producer; yields `transaction_log_provenance_unverified`). |
| `actual_outcome` | Disposition: `"answer"` or `"refusal"` | Runtime policy evaluation engine | Producer: absent in production runtime. Consumer: `eval/agent_adapter.py`, `eval/run_eval.py`. | Authoritative runtime decision branch; must never be guessed from phrasing. | Emitted only upon completed disposition. Cleared to `None` on runtime failure or `needs_information`. | `src/trfc/agent/loop.py:38`; `eval/run_eval.py:223, 235-240, 265`; `tests/test_eval.py`. | **No** (field unavailable in production runtime; remains `None`). |
| `actual_refusal_type` | Refusal classification: `"i"` (scope/corpus) or `"ii"` (insufficient evidence) | Runtime refusal policy branch | Producer: absent in production runtime. Consumer: `eval/run_eval.py`, `eval/decision_events.py`. | Grounded in DOC0009 (scope) or DOC0006/DOC0007 (retention/sync). | Applicable only when `actual_outcome == "refusal"`. Forced to `None` on `answer` or `needs_information`. | `eval/decision_events.py:40-44`; `tests/test_decision_events.py:40-49`; `tests/test_offline_policy.py:239-281`. | **No** (field unavailable in production runtime; remains `None`). |
| `policy_rule_id` | Stable identifier of matched policy rule | Policy rule registry / engine | Producer: absent. Consumer: `AgentRunResult`, `eval/decision_events.py`. | Rule ID from formal catalog (e.g. DOC article reference). | Emitted only when explicit rule match occurs. Cleared on `needs_information`. | `src/trfc/agent/loop.py:40`; `eval/decision_events.py:49-52`. | **No** (absent; remains `None`). |
| `decision_source` | Module / service asserting the decision | Trusted decision subsystem | Producer: absent in production runtime. Consumer: `eval/decision_events.py`. | Safe identifier regex `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}`. | Required for emitting any `decision_event`. Cleared on `needs_information`. | `eval/decision_events.py:45-48`; `tests/test_decision_events.py:59-67`. | **No** (absent in production runtime; remains `None`). |
| `operator_id` & `approval_ref` | Written controller authorization for freeze | Identity provider & approval workflow | Producer: absent. Consumer: write-tool guard. | Authenticated controller identity and signed authorization per DOC0008. | Must link to specific account and excess ratio alert. | `eval/agent_adapter.py:85-89`; `tests/test_offline_policy.py:102-109`. | **No** (absent; caller attempts to supply these fields are rejected as unsupported). |
| `claims` | Exact answer claims | Claim extraction subsystem | Producer: absent. Consumer: `eval/run_eval.py:faithfulness`. | Exact verbatim spans extracted from `actual_answer`. | Complete segmentation of answer assertions. Cleared on failed runs. | `src/trfc/agent/loop.py:43`; `eval/run_eval.py:230, 244`. | **No** (absent; remains `None`). |

### 3. C4-FINAL-11 verification summary

The C4-FINAL-11 audit re-verified all five tiers and confirmed that:
1. No authentic upstream producers exist for Tier 3 dependencies.
2. `eval/run_eval.py` strictly clears decision fields when `policy_decision_status == "needs_information"`, enforces `actual_refusal_type = None` on answer outcomes, and prevents failed serialized cases from entering `refusal_rows`.
3. Tier 1 outputs (`contexts`, `tool_trace`, `usage`) provide capture evidence only, and must not be conflated with policy compliance or verified database side effects.
4. C4 remains **BLOCKED** on missing authoritative sources and authentic staging evidence.
