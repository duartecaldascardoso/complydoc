# complydoc — offline document audit.
# Everything runs through uv; nothing here needs a network at run time.

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
PYTHON  ?= $(UV) run
SRC     := src/complydoc
TESTS   := tests
DOCS    ?= tests/fixtures
OUT     ?= reports

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Variables: DOCS=<path to audit>  OUT=<report dir>  VOLUME=<docs/month>"

# ---------------------------------------------------------------- setup ----

.PHONY: install
install: ## Install the base dependencies
	$(UV) sync

.PHONY: install-dev
install-dev: ## Install base plus the dev group
	$(UV) sync --group dev

.PHONY: install-all
install-all: ## Install everything, including OCR and the local NER model
	$(UV) sync --extra ocr --extra ner --group dev
	$(PYTHON) python -m spacy download en_core_web_sm

.PHONY: tool
tool: ## Install complydoc on PATH so it runs from any directory
	$(UV) tool install . --force

# ----------------------------------------------------------------- check ---

.PHONY: test
test: ## Run the test suite
	$(PYTHON) pytest

.PHONY: cov
cov: ## Run the tests with a coverage report
	$(PYTHON) pytest --cov=complydoc --cov-report=term-missing

.PHONY: lint
lint: ## Check formatting and lint rules
	$(PYTHON) ruff check $(SRC) $(TESTS)
	$(PYTHON) ruff format --check $(SRC) $(TESTS)

.PHONY: format
format: ## Apply formatting and autofixable lint rules
	$(PYTHON) ruff check --fix $(SRC) $(TESTS)
	$(PYTHON) ruff format $(SRC) $(TESTS)

.PHONY: types
types: ## Type check with mypy
	$(PYTHON) mypy $(SRC)

.PHONY: check
check: lint types test ## Everything CI would run

# ------------------------------------------------------------------ run ----

.PHONY: audit
audit: ## Audit DOCS (default: the test fixtures) into OUT
	$(PYTHON) complydoc audit $(DOCS) --ocr --out $(OUT) \
		$(if $(VOLUME),--monthly-volume $(VOLUME),)

.PHONY: sensitive
sensitive: ## Run only the sensitive data scan over DOCS
	$(PYTHON) complydoc sensitive $(DOCS) --ocr --out $(OUT)

.PHONY: doctor
doctor: ## Report what is installed and what is missing
	$(PYTHON) complydoc doctor

.PHONY: models
models: ## List the models available to price against
	$(PYTHON) complydoc models

# ---------------------------------------------------------------- assets ---

.PHONY: fixtures
fixtures: ## Rebuild the committed test fixtures
	$(PYTHON) python $(TESTS)/generate_fixtures.py

.PHONY: diagrams
diagrams: ## Re-export the README architecture diagrams to SVG
	$(PYTHON) python scripts/build_diagram.py

# ----------------------------------------------------------------- misc ----

.PHONY: build
build: ## Build the wheel and sdist
	$(UV) build

.PHONY: clean
clean: ## Remove caches, build output and generated reports
	rm -rf $(OUT) dist build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
