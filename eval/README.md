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
  reports an actual type `i`/`ii`. Missing outcome/type is not silently scored.

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
refusal-decision SVG charts. Missing/unscorable values remain blank/N/A; failed
questions are not converted to zero. Async adapter calls have a configurable
per-case timeout; synchronous adapters must set their own I/O timeout. SVG generation uses only the Python
standard library, so no chart dependency is added. Empty JSONL yields a header-only
CSV and charts explicitly labelled as having no evaluation data.

## Current integration limitations

- `src/trfc/agent/loop.py` currently exposes an async `run()` but its CLI calls it
  without awaiting it.
- `src/trfc/agent/llm.py` imports Groq, while `pyproject.toml` does not declare
  the Groq package. `.env.example` documents `GROQ_API_KEY` and the fallback
  `LLM_API_KEY`; credentials alone do not resolve the missing package.
- The loop supplies function-tool schemas but the current wrapper returns only
  message text and the parser expects a custom JSON action. A/B need to agree on
  one protocol and expose the result fields above.
- The loop currently discards usage and does not return a structured per-question
  trace/context/refusal classification. A C adapter cannot safely infer these.
- No genuine run logs are included. C4 remains pending until real scenarios run.
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
Agent/LLM calls read `GROQ_API_KEY`, falling back to `LLM_API_KEY`, and may
override the model with `LLM_MODEL`. A working Groq credential/service and the
undeclared `groq` package are needed for the current LLM wrapper.

Report generation reads an existing evaluation JSONL; it does not run the
agent. It creates `evaluation.csv`, `faithfulness.svg`, and
`refusal_correctness.svg` under the selected output directory. Empty data gives
a header-only CSV and charts labelled “No evaluation data”; absent metric or
usage values remain blank/N/A, not zero. No genuine run logs are included, so
do not treat `make demo`, a real evaluation, or report values as verified until
the A/B integration and real scenarios have run.
