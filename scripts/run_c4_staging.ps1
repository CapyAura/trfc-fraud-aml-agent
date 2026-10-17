# Staging execution runner for C4
$ErrorActionPreference = "Stop"
$STAMP = (Get-Date).ToString("yyyyMMdd_HHmmss")
Write-Output "=== C4 REAL STAGING PIPELINE LAUNCH ==="
Write-Output "Timestamp: $STAMP"

$ISOLATED_DIR = "D:\Work\AIPR\staging_c4_$STAMP"
$DB_FILE = "$ISOLATED_DIR\state.db"
$LOG_DIR = "logs\staging_$STAMP"

if (Test-Path $ISOLATED_DIR) { throw "Collision: $ISOLATED_DIR already exists!" }
if (Test-Path $LOG_DIR) { throw "Collision: $LOG_DIR already exists!" }

New-Item -ItemType Directory -Path $ISOLATED_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
Write-Output "Isolated DB Dir: $ISOLATED_DIR"
Write-Output "Log Dir: $LOG_DIR"

$PROD_HASH_BEFORE = (Get-FileHash -Path "data\state.db" -Algorithm SHA256).Hash
Write-Output "Production DB Hash Before: $PROD_HASH_BEFORE"

$env:TRFC_REQUIRE_ISOLATED_DB = "1"
$env:TRFC_STATE_DB = $DB_FILE
$env:TRFC_REQUIRE_OUTSIDE_REPO = "1"
$env:TRFC_PREVENT_DB_OVERWRITE = "1"
$env:PYTHONPATH = "."
$env:CASE_INTERVAL_SECONDS = "5"

Write-Output "=== SEEDING ISOLATED DATABASE ==="
& .venv\Scripts\python.exe -c "import trfc.tools.state as s; s.reset(); print('Isolated DB seeded at:', s.resolve_db_path())"
if ($LASTEXITCODE -ne 0) { throw "DB Seeding failed with exit code $LASTEXITCODE" }

$PROD_HASH_AFTER_SEED = (Get-FileHash -Path "data\state.db" -Algorithm SHA256).Hash
if ($PROD_HASH_BEFORE -ne $PROD_HASH_AFTER_SEED) { throw "CRITICAL: Production data/state.db was modified during seeding!" }
Write-Output "Production DB Hash verified untouched after seed."

Write-Output "=== RUNNING REAL EVALUATION (12 cases) ==="
$evalOut = "$LOG_DIR\evaluation.jsonl"
$stepEventsOut = "$LOG_DIR\step_events.jsonl"
$decisionEventsOut = "$LOG_DIR\decision_events.jsonl"
$judgeOut = "$LOG_DIR\judge.jsonl"

# --judge runs the LLM judge on the unredacted row inside the evaluator. It is a
# second, independent measurement: judge_* columns are added beside the
# deterministic metrics and never replace them.
& .venv\Scripts\python.exe -m eval.run_eval `
  --testset tests\testset.jsonl `
  --output "$evalOut" `
  --step-events-output "$stepEventsOut" `
  --decision-events-output "$decisionEventsOut" `
  --agent-adapter eval.agent_adapter:run_case `
  --execution-mode real `
  --judge

$evalExit = $LASTEXITCODE
Write-Output "Evaluation exit code: $evalExit"

$PROD_HASH_AFTER_EVAL = (Get-FileHash -Path "data\state.db" -Algorithm SHA256).Hash
if ($PROD_HASH_BEFORE -ne $PROD_HASH_AFTER_EVAL) { throw "CRITICAL: Production data/state.db was modified during evaluation!" }
Write-Output "Production DB Hash verified untouched after evaluation."

if ($evalExit -ne 0) {
    Write-Output "Evaluation returned non-zero exit code: $evalExit. Halting pipeline."
    exit $evalExit
}

Write-Output "=== POST-EVALUATION DATA ASSERTIONS ==="
& .venv\Scripts\python.exe -c @"
import json, sys
with open(r'$evalOut', 'r', encoding='utf-8') as f:
    rows = [json.loads(line) for line in f if line.strip()]
print('Evaluated rows count:', len(rows))
assert len(rows) == 12, f'Expected 12 cases, got {len(rows)}'
case_ids = {r.get('question_id') for r in rows}
expected = {f'q{i:02d}' for i in range(1, 13)}
assert case_ids == expected, f'Case IDs mismatch: {case_ids}'
for r in rows:
    assert r.get('status') == 'completed', f'Case {r.get(\"question_id\")} status: {r.get(\"status\")}'
    assert r.get('error') is None, f'Case {r.get(\"question_id\")} error: {r.get(\"error\")}'
print('All 12 cases completed successfully with 0 errors.')
"@
if ($LASTEXITCODE -ne 0) { throw "Post-evaluation assertions failed!" }

Write-Output "=== LOG SCHEMA VALIDATION ==="
& .venv\Scripts\python.exe -m eval.log_validation "$evalOut" --kind case
if ($LASTEXITCODE -ne 0) { throw "Evaluation log validation failed!" }
& .venv\Scripts\python.exe -m eval.log_validation "$stepEventsOut" --kind event
if ($LASTEXITCODE -ne 0) { throw "Step events validation failed!" }
& .venv\Scripts\python.exe -m eval.log_validation "$decisionEventsOut" --kind decision
if ($LASTEXITCODE -ne 0) { throw "Decision events validation failed!" }
Write-Output "All 3 schema validations PASSED."

Write-Output "=== SEMANTIC GATE EXECUTION ==="
$gateOut = "$LOG_DIR\semantic_gate_result.json"
& .venv\Scripts\python.exe -m eval.semantic_gate "$LOG_DIR" `
  --step-events "$stepEventsOut" `
  --decision-events "$decisionEventsOut" `
  --require-events `
  --output "$gateOut"

$gateExit = $LASTEXITCODE
Write-Output "Semantic Gate exit code: $gateExit"
if ($gateExit -ne 0) { throw "Semantic Gate FAILED with exit code $gateExit" }

Write-Output "=== GENERATING FINAL REPORT ==="
& .venv\Scripts\python.exe -m eval.report --input "$evalOut" --output-dir "$LOG_DIR\reports" --rescore

Write-Output "=== JUDGE SUMMARY ==="
& .venv\Scripts\python.exe -c @"
import json
rows = [json.loads(line) for line in open(r'$evalOut', encoding='utf-8') if line.strip()]
judged = [r for r in rows if r.get('judge_faithfulness') is not None]
errors = [r for r in rows if r.get('judge_error')]
print(f'judged={len(judged)}/{len(rows)} errors={len(errors)}')
for r in rows:
    print(f\"  {r['question_id']}: det={r['metrics'].get('faithfulness')} \"
          f\"judge={r.get('judge_faithfulness')} outcome={r.get('judge_outcome')} \"
          f\"err={r.get('judge_error')}\")
"@
Write-Output "=== STAGING PIPELINE COMPLETED SUCCESSFULLY ==="
