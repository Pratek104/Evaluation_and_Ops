.PHONY: install run mcp test lint format typecheck check reset-db verify-seed eval eval-retrieval eval-report docker-build

install:
	python -m pip install -r requirements-dev.txt

run:
	python -m streamlit run streamlit_app.py

mcp:
	python -m xyz_portal.mcp_server

test:
	python -m pytest

lint:
	python -m ruff check .

format:
	python -m ruff format .

typecheck:
	python -m mypy src

check: lint typecheck test

reset-db:
	python scripts/reset_demo_data.py --yes

verify-seed:
	python scripts/verify_seed.py

eval:
	python evals/run_all.py

eval-retrieval:
	python evals/run_rag_eval.py --dry-run

eval-report:
	python evals/export_csv.py

docker-build:
	docker build -t xyz-employee-portal .
