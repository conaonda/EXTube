.PHONY: lint test test-e2e test-integration format install dev coverage

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

test-integration:
	docker compose -f docker/docker-compose.test.yml up -d --build
	@echo "Waiting for services..."
	@for i in $$(seq 1 30); do \
		if curl -sf http://localhost:8099/health > /dev/null 2>&1; then \
			echo "Services ready"; \
			break; \
		fi; \
		sleep 2; \
	done
	pytest tests/integration/ -v --tb=short; \
	EXIT_CODE=$$?; \
	docker compose -f docker/docker-compose.test.yml down -v; \
	exit $$EXIT_CODE

coverage:
	pytest --cov=src --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-report=term-missing --cov-fail-under=70 -v
