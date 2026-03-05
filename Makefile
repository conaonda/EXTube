.PHONY: lint test test-e2e format install dev

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

lint:
	ruff check src/ tests/ --exclude src/viewer/
	ruff format --check src/ tests/ --exclude src/viewer/
	cd src/viewer && npx eslint .

format:
	ruff check --fix src/ tests/ --exclude src/viewer/
	ruff format src/ tests/ --exclude src/viewer/
	cd src/viewer && npx prettier --write src/

test:
	pytest -v

test-e2e:
	pytest -v -m e2e
