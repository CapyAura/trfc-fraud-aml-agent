ifeq ($(OS),Windows_NT)
# Ghim shell: không ghim thì make lấy SHELL từ môi trường, nên chạy từ cmd.exe thì
# được còn chạy từ Git Bash thì sh nuốt mất dấu "\" trong đường dẫn.
SHELL := cmd.exe
.SHELLFLAGS := /c
# cmd.exe hiểu "/" là dấu switch -> ".venv/Scripts/python.exe" bị đọc thành lệnh ".venv".
PY := .venv\Scripts\python.exe
MKDIR := $(PY) -c "import os; os.makedirs('.test-tmp', exist_ok=True)"
DEMO_ENV := chcp 65001 >nul && set "TRFC_REQUIRE_ISOLATED_DB=1" && set "TRFC_STATE_DB=%TEMP%\trfc-demo-state.db" &&
# Câu hỏi nằm ở scripts/demo_question.txt (UTF-8) chứ không nằm trong Makefile: cmd.exe
# đọc command line theo codepage ANSI (cp1258) nên tiếng Việt trong recipe bị vỡ font.
DEMO_RUN := $(PY) -c "import sys,pathlib;from trfc.agent.loop import main;sys.argv=['loop','--pretty',pathlib.Path('scripts/demo_question.txt').read_text(encoding='utf-8')];raise SystemExit(main())"
# Log MCP server bắn ra stderr (INFO mỗi tool call) -> đẩy vào file cho sạch màn hình,
# nhưng vẫn in ra khi lệnh fail để không giấu lỗi.
DEMO_LOG := "%TEMP%\trfc-demo.log"
DEMO := $(DEMO_ENV) $(DEMO_RUN) 2>$(DEMO_LOG) || (echo.& echo --- LOI, log ky thuat: $(DEMO_LOG)& type $(DEMO_LOG)& exit /b 1)
else
PY := .venv/bin/python
MKDIR := mkdir -p .test-tmp
DEMO_ENV := TRFC_REQUIRE_ISOLATED_DB=1 TRFC_STATE_DB=$${TMPDIR:-/tmp}/trfc-demo-state.db
DEMO_RUN := $(PY) -m trfc.agent.loop --pretty "$$(cat scripts/demo_question.txt)"
DEMO_LOG := $${TMPDIR:-/tmp}/trfc-demo.log
DEMO := $(DEMO_ENV) $(DEMO_RUN) 2>$(DEMO_LOG) || { echo; echo "--- LOI, log ky thuat: $(DEMO_LOG)"; cat $(DEMO_LOG); exit 1; }
endif

.PHONY: setup demo eval eval-live validate-testset report test

# Phiên chạy thật dùng để tái lập số liệu report. Đổi phiên: make eval SESSION=logs/<dir>
SESSION ?= logs/staging_20261017_201308

setup:
	uv sync --locked --extra dev

# Demo chạy trên DB dùng-một-lần ngoài repo: state.reset() xoá rồi seed lại mỗi
# lần nên lặp lại được, và data/state.db production không bị đụng. Câu hỏi tự
# chứa số liệu vì seed cố định ở 2026-10-09 và system prompt không được nạp ngày
# hiện tại — hỏi "hôm nay" thì get_transactions luôn trả rỗng, agent từ chối và
# không lộ được tầng (c) write → verify.
demo:
	@$(DEMO_ENV) $(PY) -c "import trfc.tools.state as s; s.reset()"
	@$(DEMO)

# Tái lập MỌI số liệu trong report từ log phiên chạy thật đã commit — không gọi
# LLM, không cần key. Ba bước: (1) validate testset, (2) chấm lại evaluation.jsonl
# của phiên thành CSV/SVG rồi so với bản đã commit, (3) chạy lại semantic gate.
# Lệch một ô là fail. Muốn chạy lại agent thật thì dùng `make eval-live`.
eval validate-testset:
	@echo [1/3] Validate testset schema (no scores yet - this step is not the evaluation)
	@$(PY) -m eval.run_eval --dry-run
	@echo.
	@echo [2/3] Rescore real run $(SESSION) and byte-compare with eval/reports
	@$(PY) -m eval.report --input $(SESSION)/evaluation.jsonl --output-dir .test-tmp/eval-repro --rescore
	@$(PY) -c "import filecmp,sys; from pathlib import Path; a,b=Path('eval/reports'),Path('.test-tmp/eval-repro'); bad=[f.name for f in sorted(b.iterdir()) if not filecmp.cmp(f, a/f.name, shallow=False)]; print('LECH: '+', '.join(bad) if bad else 'eval-repro: khop tung byte voi eval/reports'); sys.exit(1 if bad else 0)"
	@echo.
	@echo [3/3] Re-run semantic gate (citations, refusals, write+verify)
	@$(PY) -m eval.semantic_gate $(SESSION) --require-events --step-events $(SESSION)/step_events.jsonl --decision-events $(SESSION)/decision_events.jsonl --output .test-tmp/eval-gate.json

# Live evaluation: calls the agent + LLM through MCP and rewrites the logs that
# feed `make report`. Needs credentials/network and an isolated TRFC_STATE_DB
# (the evaluator fails closed otherwise). On Windows run via Git Bash/WSL or use
# the equivalent `python -m eval.run_eval` command from README.md.
eval-live:
	$(PY) -m eval.run_eval --agent-adapter eval.agent_adapter:run_case \
		--output logs/evaluation.jsonl
	$(PY) -m eval.report --input logs/evaluation.jsonl --output-dir eval/reports --rescore

report:
	$(PY) -m eval.report --input logs/evaluation.jsonl --output-dir eval/reports

test:
	$(MKDIR)
	$(PY) -m pytest --ignore=tests/test_tools.py --basetemp .test-tmp/pytest
