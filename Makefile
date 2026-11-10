PYTEST_ARGS ?=
.PHONY: report install check lint types layers test unit integration acceptance run
install:
	uv sync
	uv run playwright install chromium
check: lint types layers test
lint:
	uv run ruff check . && uv run ruff format --check .
types:
	uv run pyright
layers:
	uv run lint-imports
test:
	uv run pytest $(PYTEST_ARGS)
unit:
	uv run pytest tests/unit
integration:
	uv run pytest tests/integration
acceptance:
	uv run pytest tests/acceptance $(PYTEST_ARGS)
run:
	uv run uvicorn previewit.bootstrap:create_app --factory --reload

report:
	mkdir -p reports
	uv run pytest $(PYTEST_ARGS) --cov=previewit --cov-branch --cov-report=term-missing \
	  --cov-report=html:reports/coverage --junitxml=reports/junit.xml \
	  --html=reports/pytest-report.html --self-contained-html
