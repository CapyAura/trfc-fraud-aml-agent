ifeq ($(OS),Windows_NT)
PY := .venv/Scripts/python.exe
else
PY := .venv/bin/python
endif

.PHONY: setup demo eval validate-testset report test

setup:
	uv sync --locked --group dev

# Blocked until the A/B agent CLI and LLM dependency/runtime are verified.
demo:
	$(PY) -m trfc.agent.loop "ACC001 hôm nay có vượt hạn mức không?"

# Offline validation only; a real evaluation requires a working adapter.
eval validate-testset:
	$(PY) -m eval.run_eval --dry-run

report:
	$(PY) -m eval.report --input logs/evaluation.jsonl --output-dir eval/reports

test:
	$(PY) -m pytest --ignore=tests/test_tools.py --basetemp .test-tmp/pytest
