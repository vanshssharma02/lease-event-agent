.PHONY: help test smoke eval seed run api ui lint clean

help:
	@echo "Available commands for lease-event-agent:"
	@echo "  make test   - Run full pytest test suite"
	@echo "  make smoke  - Run isolated automated smoke test"
	@echo "  make eval   - Run benchmark evaluation harness"
	@echo "  make seed   - Seed database and generate lease PDFs"
	@echo "  make run    - Run batch agent over in-window leases"
	@echo "  make api    - Launch FastAPI backend (port 8000)"
	@echo "  make ui     - Launch Streamlit UI (port 8501)"
	@echo "  make lint   - Run ruff code quality checks"
	@echo "  make clean  - Clean cache and temporary files"

test:
	python -m pytest tests/ -v

smoke:
	python scripts/smoke_test.py

eval:
	python -m eval.run_eval --runs 3

seed:
	python -m app.seed

run:
	python -m app.run

api:
	python -m uvicorn app.api:app --reload --port 8000

ui:
	python -m streamlit run ui/streamlit_app.py

lint:
	python -m ruff check app/ ui/ eval/ tests/ scripts/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
