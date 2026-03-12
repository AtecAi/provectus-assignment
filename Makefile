.PHONY: setup run test generate ingest clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
STREAMLIT := $(VENV)/bin/streamlit

setup: $(VENV) install generate ingest

$(VENV):
	python3 -m venv $(VENV)

install: $(VENV)
	$(PIP) install -r requirements.txt

generate: $(VENV)
	$(PYTHON) generate_fake_data.py --num-users 100 --num-sessions 5000 --days 60 --seed 42

ingest: $(VENV)
	$(PYTHON) -m src.ingestion.pipeline

run: $(VENV)
	PYTHONPATH=$(CURDIR) $(STREAMLIT) run src/dashboard/app.py

api: $(VENV)
	PYTHONPATH=$(CURDIR) $(VENV)/bin/uvicorn src.api.main:app --reload --port 8000

test: $(VENV)
	$(PYTHON) -m pytest tests/ -v

clean:
	rm -rf output/ $(VENV) *.duckdb *.duckdb.wal
