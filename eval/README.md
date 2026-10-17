# Evaluation contract (Person C)

## Testset

`tests/testset.jsonl` contains exactly 12 JSON objects, one per line:

| Category | Count | Purpose |
|---|---:|---|
| `retrieval` | 3 | Single-document lookup |
| `calc` | 2 | Threshold arithmetic grounded in corpus figures |
| `contradiction` | 2 | Geographic rule and policy version/date |
| `multi_doc` | 1 | Synthesis across documents |
| `no_answer` | 4 | Two type `i` corpus/scope refusals and two type `ii` missing-evidence refusals |

Required fields include `id`, `question`, `category`, `allowed_to_answer`,
`expected_outcome`, `expected`, and `source_refs`. Answerable cases use explicit
`expected.criteria_type="contains_all"` markers. These markers are a deterministic
minimum check, not a semantic answer judge. Refusal cases carry `refusal_type`
(`i` or `ii`), `missing_evidence` where applicable, and source references for the
scope/evidence rule.

Validate without importing the agent or calling an API:

```powershell
python -m eval.run_eval --dry-run
```

## Metrics and limitations

- **Faithfulness:** fraction of explicitly supplied `claims` found literally in
  both the actual answer and retrieved context (case-insensitive). Claims absent
  from the answer make the metric unscorable, preventing a caller from scoring
  unrelated text. This does not recognize paraphrases or prove entailment.
  Without claim segmentation, answer, or context, the value is `null`/unscorable.
- **Context precision:** fraction of retrieved contexts whose `DOCnnnn` ID is in
  the question's `source_refs`. This checks source relevance labels, not semantic
  relevance within a document. Missing references/context or a missing DOC ID
  are unscorable rather than counted as irrelevant.
- **Answer correctness:** checks every literal marker in `expected.values` for
  `contains_all` cases. It is deterministic and intentionally conservative.
- **Correct refusal/decision rate:** checks answer versus refusal against
  `allowed_to_answer`; refusal subtype is scored separately only when the runtime
  reports an actual refusal and its type `i`/`ii`. Missing outcome/type is not silently scored.

No LLM judge is used. These metrics must not be presented as RAGAS scores or as
semantic proof. The project course brief mentions answer relevance as a general
evaluation requirement; it is not claimed by this implementation.

## Runtime adapter and evaluation JSONL

The built-in adapter `eval.agent_adapter:run_case` calls the existing
`run_detailed(question)` interface once and maps its `AgentRunResult` fields
without deriving metadata from answer text. This preserves structured status,
error, usage, retrieval contexts, and trace state where the runtime captured
them. The adapter does not call the public `run(question) -> str` path and does
not execute the agent twice. `run(question)` remains unchanged for existing
callers.

`run_detailed()` currently leaves `actual_outcome`, `actual_refusal_type`,
`policy_rule_id`, `decision_source`, and `claims` unavailable (`null`), so
successful executions remain unscorable for decision-dependent metrics;
refusal subtype and faithfulness also remain unscorable. A literal answer prefix such as `Error: ` is not treated as an
error; structured runtime `status` determines failure. The detailed interface
is provisional in runtime source, but the evaluator has selected and implemented
its existing `AgentRunResult` contract without changing `run(question)`. Coordinate
with Person B before changing that runtime interface. The source contract and
comparison with other options are in
[`PERSON_B_C4_METADATA_CONTRACT.md`](PERSON_B_C4_METADATA_CONTRACT.md).

`eval.agent_adapter.build_adapter(model_request, mode=..., provider_id=...)`
provides explicit provider injection for offline evaluation. It forwards the
provider to `run_detailed()` and accepts only `mock`, `unit_test`, or
`synthetic` provenance. The default `run_case` adapter remains bound to the
runtime's existing default provider. `run(question) -> str` remains unchanged.

For deterministic policy-contract checks, `eval.agent_adapter:offline_policy_case`
is a separate adapter registered as `synthetic`. It requires a structured
`policy_request` (`intent`, evidence reference, and the relevant typed policy
fact); it never parses the question or answer, calls the LLM/MCP agent, or
executes database tools. `trfc.agent.offline.run_policy_offline()` is its runtime
entry point. DOC0009 Arts. 3–5 and DOC0007 Art. 12 identify which structured
facts would be relevant, but the project has no authenticated source for the
caller-provided method classification or log-retention status. The runtime
therefore returns `needs_information` and does not populate outcome, refusal
subtype, rule ID, or decision source. Freeze and Flag remain blocked pending
authenticated approval and a structured rule-match source. Claims and provider
usage remain unavailable. These tests carry synthetic provenance and are not
genuine production C4 evidence.

For the built-in detailed adapter, `tool_trace: null` means
unavailable/incomplete capture, while `tool_trace: []` means capture completed
and there were no tool calls. Populated lists may contain complete or partial
captured calls, and status must preserve whether execution failed. The current
runtime emits these states according to its current capture lifecycle; they are
passed through without converting `null` to `[]`.

Each output JSONL row includes timestamp, case ID/category, expected outcome and
references, actual fields, metrics, error, and status (`completed`, `failed`, or
`unscorable`). Missing usage stays `null`, not zero. A runtime failure is
`failed`; absent decision metadata leaves a successful execution `unscorable`;
a not-applicable metric (for example refusal subtype on an answer outcome) stays
null. Optional `policy_rule_id` and `decision_source` fields are copied from the
runtime result when present; the evaluator does not derive them. Failures are
written per case and do not prevent later cases.

```powershell
$env:TRFC_STATE_DB = Join-Path $env:TEMP ("trfc-eval-" + [guid]::NewGuid() + ".db")
$env:TRFC_REQUIRE_ISOLATED_DB = "1"
python -m eval.run_eval --agent-adapter eval.agent_adapter:run_case --output logs/evaluation.jsonl
```

That command invokes the agent and writes evaluation output; it requires a
working Groq/MCP runtime, credentials, and an environment where asyncio works.
The dry run only validates the testset, produces no scores or output file, and
needs neither `.env` nor credentials. Adapter tests use fake responses; they do
not establish real Groq/MCP behavior or subprocess database isolation.

## CSV and charts

After a real evaluation has written JSONL:

```powershell
python -m eval.report --input logs/evaluation.jsonl --output-dir eval/reports
```

The script reads actual JSONL and writes a per-question CSV plus faithfulness and
refusal-decision SVG charts. Missing metric keys are labelled Missing; explicit
null or invalid metric values are labelled Unscorable; answerable-case refusal
subtypes are N/A. Failed questions are not converted to zero. Async adapter calls have a configurable
per-case timeout. The built-in agent offloads its synchronous Groq request to a
worker thread so that timeout handling can run; cancelling the await does not stop
an in-flight request or retry sleep, so this is a soft bound on the evaluator, not
a hard bound on provider work. Custom adapters that block the event loop cannot be
bounded this way and must use cancellable async I/O or their own isolation.
SVG generation uses only the Python standard library, so no chart dependency is added. Empty JSONL yields a header-only
CSV and charts explicitly labelled as having no evaluation data.

## Current integration limitations

- `src/trfc/agent/loop.py` exposes an async `run()` function, and its CLI now
  invokes it using `asyncio.run(...)`.
- `src/trfc/agent/llm.py` uses Groq. The `groq` dependency is declared in
  `pyproject.toml` and `uv.lock`. The configured environment loads
  `GROQ_API_KEY`, with `LLM_API_KEY` as a fallback.
- The loop uses Groq's structured native `tool_calls` response and sends MCP
  results back with their matching tool-call IDs. Groq's current official model
  documentation lists the configured default `qwen/qwen3.8-27b` as supporting
  Tool Use ([model page](https://console.groq.com/docs/model/qwen/qwen3.8-27b),
  [tool-use support matrix](https://console.groq.com/docs/tool-use/overview)),
  but this repository has not verified a live request or endpoint access. The
  local path has fake-based unit coverage only.
- `run(question)` returns a string and remains unchanged. `run_detailed()` returns
  the provisional `AgentRunResult` dataclass with status, error, trace, usage,
  contexts and answer. The built-in evaluator adapter maps this result once per
  case. Person B has not yet confirmed it as a stable integration contract.
  Neither API currently supplies authoritative outcome/refusal subtype or
  claims; those metrics remain unscorable until an agreed runtime source exists.
- A real evaluation now fails closed unless `TRFC_REQUIRE_ISOLATED_DB=1` and an
  absolute `TRFC_STATE_DB` path are set. The evaluator rejects a path that
  resolves to the default `data/state.db` before creating output or invoking the
  adapter. Use a disposable SQLite database; the configured path is passed to
  the MCP child process by the agent runtime. This check validates configuration
  only: it does not itself prove which database a subprocess opened. Direct
  write-capable tools have a separate fail-closed guard in
  `src/trfc/tools/state.py`; evaluator preflight does not replace that guard.
  Neither check proves which database a real MCP subprocess opened. Do not use
  `state.reset()` without an explicit disposable database path.
- Authentic run logs from staging verification are included in
  `logs/staging_20261017_201308/` covering all 12 testset cases across freeze,
  flag, and refusal scenarios.
- The proposed runtime metadata interface for Person B review is documented in
  [`PERSON_B_C4_METADATA_CONTRACT.md`](PERSON_B_C4_METADATA_CONTRACT.md). It is
  a proposal, not an agreed runtime implementation.
- The built-in runtime currently has no authoritative source for
  `actual_outcome`, `actual_refusal_type`, or `claims`; those fields remain
  unavailable and dependent metrics are unscorable where applicable. The
  metadata contract still requires Person B confirmation.
- Evaluation JSONL redaction is best-effort. It handles known sensitive field
  names and common credential/identifier patterns, but cannot guarantee
  detection of arbitrary sensitive text. Review before retaining logs.
- The built-in evaluator timeout is soft: its synchronous Groq request runs in
  a worker thread so the event loop can record the timeout and continue, but
  cancellation does not stop the request or retry sleeps already in progress.
  No hard process timeout is implemented.
- C6's independent client uses the project's MCP stdio SDK, discovers tool names
  and schemas at runtime, and only calls a tool explicitly selected with
  `--tool`. Run from the project root, for example:

  ```powershell
  python -m trfc.mcp_server.client2 --tool search_policy --arguments '{"query":"transaction limits"}'
  ```

  Unit tests use fake sessions. A real-server interoperability run is not
  claimed by those tests. The server also exposes write tools, so select a
  read-only tool for a manual smoke check unless a state-changing call is
  intentionally required. The client forwards a resolved `TRFC_STATE_DB` and
  `TRFC_REQUIRE_ISOLATED_DB` to its server subprocess when configured.

  Run C6 unit tests with `python -m unittest discover -s tests -p test_client2.py -v`.

## Reproducibility notes

The project declares Python `>=3.11` in `pyproject.toml` and has a `uv.lock`.
Install locked runtime and test dependencies from the repository root with:

```powershell
uv sync --locked --group dev
```

Then run the offline checks with `make test` and `make eval`, or invoke the
virtual-environment Python directly on Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest --ignore=tests/test_tools.py --basetemp .test-tmp/pytest
.\.venv\Scripts\python.exe -m eval.run_eval --dry-run
```

The current `make test` command excludes `tests/test_tools.py`; that file's
current fixture uses a database under pytest's temporary directory. The target
therefore does not run that tool test module, but the fixture does not target the
repository's default database. Pytest writes temporary files under
`.test-tmp/pytest`. The offline tests and dry run need no API keys. Embedding code uses
`OPENAI_API_KEY` or `JINA_API_KEY` when configured and otherwise falls back to
offline hashing; configuring a key can cause external embedding requests.
Agent/LLM calls read `GROQ_API_KEY`, falling back to `LLM_API_KEY`, and may override the model with `LLM_MODEL`. The Groq dependency is declared in `pyproject.toml` and `uv.lock`. Live LLM calls require a valid Groq credential, network access, and an available model/service. The `.env` file should remain untracked and excluded by `.gitignore`; `.env.example` may be committed without real credentials.

Report generation reads an existing evaluation JSONL; it does not run the
agent. It creates `evaluation.csv`, `faithfulness.svg`, and
`refusal_correctness.svg` under the selected output directory. Empty data gives
a header-only CSV and charts labelled “No evaluation data”. A metric key absent
from a row is labelled `Missing`; an explicit JSON `null` or invalid metric is
labelled `Unscorable`; a valid measured value is shown as its score. Refusal
subtype is `N/A` for answerable questions. Missing usage remains blank rather
than being converted to zero. CSV fields use standard CSV escaping, and malformed
JSONL is rejected with its file and line number. No genuine run logs are included, so
do not treat `make demo`, a real evaluation, or report values as verified until
the A/B integration and real scenarios have run.

### Latest recorded verification status

The current working tree passed the full offline pytest suite on Python 3.14.7 using the project `.venv`:

- Adapter tests: **14 passed**.
- Focused regression suite: **118 passed, 1 skipped**.
- Full suite: **142 passed, 1 skipped**.
- `git diff --check` completed without whitespace errors; Git emitted only LF-to-CRLF working-copy notices.

These results establish automated test coverage only. They do not establish a live Groq request, genuine MCP subprocess isolation, or authoritative outcome/refusal/claims metadata. The `AgentRunResult` interface remains provisional pending cross-owner confirmation. No live evaluation or production database operation is claimed.

## C4 trace validation and genuine-run evidence

`python -m eval.log_validation --kind case logs` checks evaluation case rows
written by `eval.run_eval`. Every JSON object has these required keys:
`timestamp` (timezone-aware ISO-8601), `question_id`, `category`,
`expected_outcome`, `allowed_to_answer`, `expected_refusal_type`, `expected`,
`source_refs`, `actual_answer`, `actual_outcome`, `actual_refusal_type`,
`contexts`, `claims`, `tool_trace`, `usage`, `metrics`, `error`, and `status`.
`status` is `completed`, `failed`, or `unscorable`; a completed row has
`actual_outcome` equal to `answer` or `refusal`. Case-level `usage` is either
`null` (unavailable) or an object with non-negative integer `calls` and token
counters (`prompt_tokens`, `completion_tokens`, `max_prompt`) that are
non-negative integers or `null` when provider usage is unavailable. Case-level
rows pass `tool_trace` through from the adapter; optional step-event output is
separately serialized and checked against the event schema below.

C4's requested step trace is a separate record type. Validate it with
`python -m eval.log_validation --kind event path\to\run.jsonl`. Each line must
be a JSON object containing `record_type="step_event"`, timezone-aware ISO
`timestamp`, `run_id`, `question_id`, `scenario` (`freeze`, `flag`, or
`refusal`), `execution_mode` (`real`, `mock`, `dry_run`, `unit_test`, or
`synthetic`), positive integer `step`, non-empty `tool`, object `args`, a
non-null `result`, and `usage` with non-negative integer `calls` and token
counters that are non-negative integers or `null` when unavailable. The
evaluator can append events derived from an adapter's structured `tool_trace`
when `--step-events-output` is provided with a registered adapter. The event
mode is taken from the adapter registration; `--execution-mode` is optional
and acts only as a consistency check. Only cases with an explicit `scenario` field (`freeze`, `flag`, or
`refusal`) are eligible. Event output is opened in append mode; it does not
replace existing event records, and a pre-existing file is appendable only when
its lines are already valid step events (to prevent mixing case logs and event
logs). The evaluator generates an opaque `run_id` per case and a timezone-aware
timestamp per event; these identify log records but do not authenticate runtime
provenance. Tool arguments and successful results use the
existing best-effort redactor. For failed tool calls, the event keeps the
captured error status but omits free-form exception details.

For `freeze` and `flag`, a case label alone is insufficient: the captured trace
must contain the corresponding `freeze_account_temporarily` or
`flag_suspicious_tx` tool call. Such an event records only that the MCP tool
call was captured and whether that call returned or errored. Even a completed
call or acknowledgement is marked `business_outcome_verified=false`; the
current runtime does not provide authoritative business-state verification.
Refusal tool-step events require structured `actual_outcome="refusal"` and
`actual_refusal_type` (`i` or `ii`) metadata plus a captured tool trace. Answer
text is never used to infer refusal or subtype. Cases lacking these conditions
are skipped with a reason in the evaluator summary.

Decision/refusal records use a separate schema and file. When configured with
`--decision-events-output`, the evaluator appends a `decision_event` only when
the runtime adapter supplies a valid actual outcome and structured
`decision_source`; refusal additionally requires an actual subtype. The record
has no fake `tool` or `step` field. `tool_trace: []` records a complete capture
with zero tool calls; `tool_trace: null` records unavailable capture and leaves
the count null. The decision record uses the same per-case `run_id` as any tool
events from that evaluation. Validate it with
`python -m eval.log_validation --kind decision path\to\decision_events.jsonl`.
The current built-in runtime does not supply the required decision metadata,
so it skips decision-event output until an authoritative runtime source exists.
A schema-valid unit-test event is not genuine-run evidence.

The case row is serialized and written before its step events are appended. If
case serialization fails, that case produces no step events. This avoids
leaving an event that suggests a successful case record exists when it does
not.

The evaluator requires a registered adapter for step-event or decision-event
output. Its standard
registration API does not allow injected providers to claim `real`, and the
built-in adapter is explicitly registered for the runtime's default provider.
The optional CLI mode cannot override that registration. This is a
configuration/provenance guard, not cryptographic attestation: custom Python
code can intentionally misrepresent its behavior. Use `unit_test`, `mock`, or
`synthetic` only for the corresponding source of events. A missing or empty
trace produces no tool step event. The separate decision-event schema can
represent a structured refusal without a tool call; it remains unavailable until
the runtime supplies the required structured metadata. Missing usage is
also left unavailable and prevents event creation rather than being replaced by
zero. Event validation checks schema and the registered configuration; it does
not prove that a genuine provider or runtime executed. `--dry-run` never emits
events.

### Genuine scenario collection runbook (requires A/B integration)

Do not run the write scenarios against the repository's default
`data/state.db`: `freeze_account_temporarily` and `flag_suspicious_tx` mutate
SQLite state. The runtime now accepts `TRFC_STATE_DB` and passes the configured
path to its MCP child; set `TRFC_REQUIRE_ISOLATED_DB=1` to block writes when
that path is missing or resolves to the default. Before any genuine write
scenario, verify the actual MCP process accesses a dedicated disposable
database and obtain an A/B runtime that returns structured per-step events and
usage without printing secrets. Retain the original JSONL files unchanged; do
not convert test fixtures or dry-run output into real-run logs.

In an approved environment where Python asyncio and MCP stdio subprocesses
work, run the isolated read-only smoke check from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
.\.venv\Scripts\python.exe scripts\verify_mcp_isolation.py
```

The runner creates a disposable database, initializes it with `state.reset`,
launches the actual MCP server, and calls only
`get_account_risk_status("ACC001")`. A temporary child-process SQLite guard
rejects the default or any unexpected database path and records the resolved
path. The temporary directory is removed on exit. This verifies MCP/database
isolation only; it does not verify Groq or write scenarios. Do not run it in an
environment with the observed loopback/asyncio restriction.

For each scenario, record a unique run ID, scenario, case/question ID, UTC
timestamps, step index, exact tool name and redacted arguments, result, and
usage. Also retain the code revision, model/service name and version (never its
key), disposable environment/database identifier, a pre-run baseline, and
post-run verification output. Redact customer data and credentials before
retention. Hash the final log file if an integrity check is needed. Run the
event validator on each retained file; separately review execution provenance.

1. **Freeze:** in the disposable database, capture
   `get_account_risk_status(account_id)` before the run. Ask the agent to assess
   a documented high-risk account and, if justified, freeze it. The trace must
   show the actual `freeze_account_temporarily(account_id, reason)` call and
   result, followed by a read-back showing the account frozen. Preserve the
   before/after verification and tool events. Do not use the default database.
2. **Flag:** capture the account/transaction state before the run. Ask the
   agent to assess a documented suspicious transaction. The trace must show
   `flag_suspicious_tx(tx_id, reason)` and a subsequent
   `get_account_risk_status(account_id)` read-back whose `flagged_tx_ids`
   includes that transaction. Preserve before/after verification.
3. **Refusal:** use a test case whose evidence is explicitly insufficient or
   outside scope. Retain the prompt and final refusal, its actual subtype (`i`
   or `ii`), and a trace showing no freeze/flag write tool was called. This
   scenario must not change state.

At present, all three genuine scenarios remain blocked pending end-to-end
runtime integration. The CLI awaits `run()` through `asyncio.run(...)`; native
tool messages and isolated database selection are implemented and covered by
fake/unit tests, but no live Groq-to-local-MCP request has been verified. The
database isolation guard must be enabled with a disposable `TRFC_STATE_DB` for
any approved write scenario. The built-in adapter does not infer refusal
outcome or subtype, so refusal scoring still requires an established runtime
classification. No genuine scenario logs are currently present.
