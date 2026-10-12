> Xem Makefile.txt nếu máy bạn không có `make`.

PY := .venv/Scripts/python.exe
ifeq ($(OS),)
PY := .venv/bin/python
endif

.PHONY: setup demo eval test clean

setup:
	python -m venv .venv
	$(PY) -m pip install -U pip
	$(PY) -m pip install -e ".[dev]"

demo:
	$(PY) -m trfc.agent.loop "ACC001 hôm nay có vượt hạn mức không?"

eval:
	$(PY) -m eval.run_eval

test:
	$(PY) -m pytest

clean:
	rm -rf .venv __pycache__ .pytest_cache
