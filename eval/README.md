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

The repository includes the minimal adapter `eval.agent_adapter:run_case`. It
receives one case dict and calls `run_detailed(question)`, returning the runtime
fields without deriving outcome, refusal subtype, contexts, or claims from the
answer text:

```python
{
    "answer": str | None,
    "actual_outcome": "answer" | "refusal",  # or `refused: bool`
    "actual_refusal_type": "i" | "ii" | None,
    "contexts": list[str] | None,             # each context should identify DOCnnnn
    "claims": list[str] | None,               # explicit factual claim segmentation
    "tool_trace": list[dict] | None,
    "usage": {
        "calls": int, "prompt_tokens": int | None,
        "completion_tokens": int | None, "max_prompt": int | None,
    } | None,
}
```

`actual_outcome` must be supplied from a recorded runtime classification (or an
explicit boolean `refused`); the evaluator does not infer it from answer text.
Refusal subtype and claims remain unavailable. The runtime preserves contexts
only from valid serialized `search_policy` chunks containing their returned
`doc_id` and `text`; malformed or missing retrieval data remains unavailable.
`calls` counts requests issued by the runtime wrapper. Per run,
`prompt_tokens` and `completion_tokens` are provider-reported totals only, and
`max_prompt` is the largest provider-reported prompt-token count from any one
request. Any aggregate whose provider counter is missing remains null. When a
request has no provider usage object, prompt/completion totals and `max_prompt`
are all null rather than partial or fabricated values.

Each output JSONL row adds timestamp, case ID/category, expected outcome and
references, actual fields, metrics, error, and status (`completed`, `failed`, or
`unscorable`). Missing usage is written as `null`, never as fabricated zeroes.
One case failure is recorded and does not stop later cases.

Interpret these states separately: a runtime error has `status="failed"` and a
non-null `error`; a completed execution with no authoritative `actual_outcome`
has `status="unscorable"` and leaves the missing metadata null; an
inapplicable metric (for example refusal subtype on an answer outcome) is null
while the row can still be completed. Missing contexts/claims leave their
dependent metrics unscorable without being converted to zero.

```powershell
$env:TRFC_STATE_DB = Join-Path $env:TEMP ("trfc-eval-" + [guid]::NewGuid() + ".db")
$env:TRFC_REQUIRE_ISOLATED_DB = "1"
python -m eval.run_eval --agent-adapter eval.agent_adapter:run_case --output logs/evaluation.jsonl
```

That command invokes the agent and writes evaluation output; it requires a
working Groq/MCP runtime, credentials, and an environment where asyncio works.
The adapter passes unknown fields through as `null`. In particular,
`run_detailed()` currently does not establish `actual_outcome`, refusal subtype,
or claims, so those metrics remain unscorable; contexts are captured only from
valid `search_policy` results. Provider token counts remain null if Groq does
not report them. Trace lifecycle is explicit: the
runtime returns `null` before MCP discovery has succeeded, `[]` for a completed
run that made no tool calls, and captured events for runs that called tools. If
execution fails before any event is captured, the trace remains `null`; failures
after recorded events retain that partial trace. The adapter and case validator
preserve `null` as unavailable/incomplete, `[]` as completed capture with no
calls, and populated lists as captured records. A completed evaluation row may
therefore retain `tool_trace: null`; a failed row cannot claim an empty completed
trace. Explicit runtime failures are recorded by the evaluator and do not
prevent later cases from running.

The dry run only validates the testset and produces no scores or output file. It
works offline and requires neither `.env` nor an LLM credential. Adapter unit
tests use fake runtime results; they do not establish a real Groq or MCP run.

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
- `run(question)` still returns a string. `run_detailed(question)` is a
  provisional result interface that also exposes tool trace and usage. The
  built-in `eval.agent_adapter:run_case` maps this result without inferring
  outcome/refusal subtype or claims. Retrieved contexts are copied from
  successful `search_policy` chunks with their document IDs. Refusal evaluation
  therefore remains unscorable until a runtime source supplies classification.
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
- No genuine run logs are included. C4 remains pending until real scenarios
  have been executed and their logs validated.
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

The latest focused pytest attempt for timeout behavior is **blocked**, not
passed: the active Python 3.12.12 has no `pytest`, and `.venv` references a
missing uv-managed Python 3.14 interpreter. A targeted attempt did not reach a
verified assertion and was stopped. AST syntax parsing for the timeout changes
and `git diff --check` passed; the latter reported only Git's LF-to-CRLF
working-copy notices. `python -m eval.run_eval --dry-run` passed with 12 valid
cases and made no agent/API calls or scores. An earlier run reported 22 passed and 4 deselected, but
that predates the timeout change and does not verify the current working tree.
`make test` excludes `tests/test_tools.py`; excluded tests are not counted as
passed. No real evaluation, live API call, or MCP subprocess verification is
claimed here.

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
non-negative integers or `null` when provider usage is unavailable. The evaluator passes
`tool_trace` through from the adapter and does not impose a step-event schema.

C4's requested step trace is a separate record type. Validate it with
`python -m eval.log_validation --kind event path\to\run.jsonl`. Each line must
be a JSON object containing `record_type="step_event"`, timezone-aware ISO
`timestamp`, `run_id`, `question_id`, `scenario` (`freeze`, `flag`, or
`refusal`), `execution_mode` (`real`, `mock`, `dry_run`, `unit_test`, or
`synthetic`), positive integer `step`, non-empty `tool`, object `args`, a
non-null `result`, and `usage` with non-negative integer `calls` and token
counters that are non-negative integers or `null` when unavailable. The current
A/B agent does not emit these events; this validator defines
and checks the C4 capture contract, it does not create events. Both modes report
invalid JSON/schema with file and line number. A successful validation means
only that the schema is valid. A declared `execution_mode="real"` is not proof
of authenticity.

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
