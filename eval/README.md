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

The agent interface is not yet stable enough for a built-in adapter. A real run
requires `--agent-adapter module:function`; the callable receives one case dict
and returns a dict with:

```python
{
    "answer": str | None,
    "actual_outcome": "answer" | "refusal",  # or `refused: bool`
    "actual_refusal_type": "i" | "ii" | None,
    "contexts": list[str] | None,             # each context should identify DOCnnnn
    "claims": list[str] | None,               # explicit factual claim segmentation
    "tool_trace": list[dict] | None,
    "usage": {
        "calls": int, "prompt_tokens": int,
        "completion_tokens": int, "max_prompt": int,
    } | None,
}
```

Each output JSONL row adds timestamp, case ID/category, expected outcome and
references, actual fields, metrics, error, and status (`completed`, `failed`, or
`unscorable`). Missing usage is written as `null`, never as fabricated zeroes.
One case failure is recorded and does not stop later cases.

```powershell
python -m eval.run_eval --agent-adapter package.module:function --output logs/evaluation.jsonl
```

That command is conditional on an adapter matching the contract and a working
agent/runtime configuration. Without an adapter, real evaluation fails clearly.
The dry run only validates the testset and produces no scores or output file.
It works offline and requires neither `.env` nor an LLM credential. A genuine
evaluation requires an adapter tested against the stable A/B runtime, any
dependencies that adapter imports, and credentials for services it uses. No
adapter is currently supplied by this repository.

## CSV and charts

After a real evaluation has written JSONL:

```powershell
python -m eval.report --input logs/evaluation.jsonl --output-dir eval/reports
```

The script reads actual JSONL and writes a per-question CSV plus faithfulness and
refusal-decision SVG charts. Missing metric keys are labelled Missing; explicit
null or invalid metric values are labelled Unscorable; answerable-case refusal
subtypes are N/A. Failed questions are not converted to zero. Async adapter calls have a configurable
per-case timeout; synchronous adapters must set their own I/O timeout. SVG generation uses only the Python
standard library, so no chart dependency is added. Empty JSONL yields a header-only
CSV and charts explicitly labelled as having no evaluation data.

## Current integration limitations

- `src/trfc/agent/loop.py` exposes an async `run()` function, and its CLI now
  invokes it using `asyncio.run(...)`.
- `src/trfc/agent/llm.py` uses Groq. The `groq` dependency is declared in
  `pyproject.toml` and `uv.lock`. The configured environment loads
  `GROQ_API_KEY`, with `LLM_API_KEY` as a fallback.
- The loop supplies function-tool schemas, but the wrapper returns message text
  and the parser expects a custom JSON action. The LLM/MCP tool-calling protocol
  still needs end-to-end verification and agreement with Person B.
- The loop does not yet expose all the structured per-question information
  required by the evaluation adapter, including usage, retrieved contexts,
  refusal classification, and per-step tool events.
- No genuine run logs are included. C4 remains pending until real scenarios
  have been executed and their logs validated.
- C6's independent client uses the project's MCP stdio SDK, discovers tool names
  and schemas at runtime, and only calls a tool explicitly selected with
  `--tool`. Run from the project root, for example:

  ```powershell
  python -m trfc.mcp_server.client2 --tool search_policy --arguments '{"query":"transaction limits"}'
  ```

  Unit tests use fake sessions. A real-server interoperability run is not
  claimed by those tests. The server also exposes write tools, so select a
  read-only tool for a manual smoke check unless a state-changing call is
  intentionally required.

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

The safe test target skips tests/test_tools.py because B-owned tests in that
file create/reset the default data/state.db; run them only in a disposable
checkout. Pytest writes temporary files under .test-tmp/pytest. The remaining
tests and dry run need no API keys. Embedding code uses
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

## C4 trace validation and genuine-run evidence

`python -m eval.log_validation --kind case logs` checks evaluation case rows
written by `eval.run_eval`. Every JSON object has these required keys:
`timestamp` (timezone-aware ISO-8601), `question_id`, `category`,
`expected_outcome`, `allowed_to_answer`, `expected_refusal_type`, `expected`,
`source_refs`, `actual_answer`, `actual_outcome`, `actual_refusal_type`,
`contexts`, `claims`, `tool_trace`, `usage`, `metrics`, `error`, and `status`.
`status` is `completed`, `failed`, or `unscorable`; a completed row has
`actual_outcome` equal to `answer` or `refusal`. Case-level `usage` is either
`null` (unavailable) or an object with non-negative integer `calls`,
`prompt_tokens`, `completion_tokens`, and `max_prompt`. The evaluator passes
`tool_trace` through from the adapter and does not impose a step-event schema.

C4's requested step trace is a separate record type. Validate it with
`python -m eval.log_validation --kind event path\to\run.jsonl`. Each line must
be a JSON object containing `record_type="step_event"`, timezone-aware ISO
`timestamp`, `run_id`, `question_id`, `scenario` (`freeze`, `flag`, or
`refusal`), `execution_mode` (`real`, `mock`, `dry_run`, `unit_test`, or
`synthetic`), positive integer `step`, non-empty `tool`, object `args`, a
non-null `result`, and `usage` with the four non-negative integer counters
above. The current A/B agent does not emit these events; this validator defines
and checks the C4 capture contract, it does not create events. Both modes report
invalid JSON/schema with file and line number. A successful validation means
only that the schema is valid. A declared `execution_mode="real"` is not proof
of authenticity.

### Genuine scenario collection runbook (requires A/B integration)

Do not run the write scenarios against the repository's default
`data/state.db`: `freeze_account_temporarily` and `flag_suspicious_tx` mutate
SQLite state, and the current code has no supported state-database override.
First obtain an isolated disposable runtime/database and an A/B adapter that
returns structured per-step events and usage without printing secrets. Retain
the original JSONL files unchanged; do not convert test fixtures or dry-run
output into real-run logs.

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

At present, all three genuine scenarios remain blocked pending runtime
integration. The CLI now awaits `run()` through `asyncio.run(...)`, but this
alone does not establish end-to-end tool calling. The agent still needs a
verified LLM/MCP protocol, structured per-step events and usage, and a supported
isolated database configuration before freeze/flag runs can safely be
performed. Refusal evaluation also requires an adapter that supplies the
expected structured fields. No genuine scenario logs are currently present.
