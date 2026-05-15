# ─────────────────────────────────────────────────────────────
# Archmorph — Development & CI Makefile (#176)
# ─────────────────────────────────────────────────────────────
.DEFAULT_GOAL := help
SHELL := /bin/bash

# ── Variables ──
BACKEND_DIR  := backend
FRONTEND_DIR := frontend
PYTHON       := python3
PIP          := pip
NPM          := npm

# ── Phony targets ──
.PHONY: help install dev test mutation-baseline lint build clean docker-build docker-up docker-down

# ── Help ──
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Install ──
install: ## Install all dependencies (backend + frontend)
	cd $(BACKEND_DIR) && $(PIP) install -r requirements.txt
	cd $(FRONTEND_DIR) && $(NPM) ci

install-backend: ## Install backend dependencies only
	cd $(BACKEND_DIR) && $(PIP) install -r requirements.txt

install-frontend: ## Install frontend dependencies only
	cd $(FRONTEND_DIR) && $(NPM) ci

# ── Development ──
dev: ## Start backend + frontend in parallel (Ctrl-C to stop)
	@echo "Starting backend on :8000 and frontend on :5173…"
	@trap 'kill 0' INT; \
		(cd $(BACKEND_DIR) && uvicorn main:app --reload --port 8000) & \
		(cd $(FRONTEND_DIR) && $(NPM) run dev) & \
		wait

dev-backend: ## Start backend only (hot-reload)
	cd $(BACKEND_DIR) && uvicorn main:app --reload --port 8000

dev-frontend: ## Start frontend only (Vite dev server)
	cd $(FRONTEND_DIR) && $(NPM) run dev

# ── Testing ──
test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests (pytest)
	cd $(BACKEND_DIR) && $(PYTHON) -m pytest tests/ -q

test-frontend: ## Run frontend tests (Vitest)
	cd $(FRONTEND_DIR) && $(NPM) test -- --run

test-e2e: ## Run Playwright E2E tests
	npx playwright test

mutation-baseline: ## Run backend mutation baseline gate for critical modules
	cd $(BACKEND_DIR) && mkdir -p ../mutation-results && \
	for module in session_store job_queue diagram_export export_capabilities iac_generator services/azure_pricing vision_analyzer; do \
		rm -rf .mutmut-cache; \
		case "$$module" in \
			session_store) tests="tests/test_session_store.py" ;; \
			job_queue) tests="tests/test_job_queue.py" ;; \
			diagram_export) tests="tests/test_diagram_export.py" ;; \
			export_capabilities) tests="tests/test_export_capabilities.py" ;; \
			vision_analyzer) tests="tests/test_vision_analyzer.py" ;; \
			iac_generator) tests="tests/test_iac_generator.py" ;; \
			services/azure_pricing) tests="tests/test_pricing_blob.py" ;; \
		esac; \
		$(PYTHON) -m mutmut run --paths-to-mutate "$$module.py" --runner "$(PYTHON) -m pytest -q $$tests" || true; \
		module_report_name="$${module//\//_}"; \
		$(PYTHON) -m mutmut results --all > "../mutation-results/$$module_report_name.txt" || true; \
	done
	$(PYTHON) scripts/mutation_score_gate.py --baseline docs/testing/mutation-baseline.json --report-dir mutation-results

# ── Linting ──
lint: lint-backend ## Run all linters

lint-backend: ## Lint backend (ruff + bandit)
	cd $(BACKEND_DIR) && ruff check . && bandit -r . -x ./tests --skip B101

# ── Build ──
build: build-frontend ## Build production assets

build-frontend: ## Build frontend for production
	cd $(FRONTEND_DIR) && $(NPM) run build

# ── Docker ──
docker-build: ## Build Docker image for backend
	docker build -t archmorph-api $(BACKEND_DIR)

docker-up: ## Start full stack via docker-compose
	docker compose up --build -d

docker-down: ## Stop docker-compose stack
	docker compose down

# ── Cleanup ──
clean: ## Remove build artifacts & caches
	find $(BACKEND_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find $(BACKEND_DIR) -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/.coverage
	rm -rf $(FRONTEND_DIR)/dist $(FRONTEND_DIR)/node_modules/.vite
