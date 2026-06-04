.PHONY: install start test lint clean migrate

# ── Defaults ────────────────────────────────────────────────────────────────
PYTHON    := uv run python3
UV        := uv
UVICORN   := uv run uvicorn

# ── Install ─────────────────────────────────────────────────────────────────
install:
	$(UV) sync
	@echo "✅ Dependencies installed"

# ── Setup ───────────────────────────────────────────────────────────────────
setup:
	$(PYTHON) scripts/setup.py

# ── Start ───────────────────────────────────────────────────────────────────
start:
	bash scripts/run.sh

# ── Start (dev, no auto-setup) ─────────────────────────────────────────────
dev:
	$(UVICORN) backend.main:app --host 0.0.0.0 --port 8080 --reload

# ── Test ────────────────────────────────────────────────────────────────────
test:
	$(PYTHON) -m pytest tests/ -v

# ── Lint ────────────────────────────────────────────────────────────────────
lint:
	$(PYTHON) -c "import py_compile; import sys, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('backend/**/*.py', recursive=True) + glob.glob('scripts/*.py')]; print('✅ Syntax check passed')"

# ── Migrate / seed ──────────────────────────────────────────────────────────
migrate:
	$(PYTHON) -c "import asyncio; from backend.database import init_db; from backend.services.app_config_service import get_app_config_service; asyncio.run(init_db()); asyncio.run(get_app_config_service().seed_defaults())"

# ── Clean ───────────────────────────────────────────────────────────────────
clean:
	rm -rf __pycache__ backend/__pycache__ backend/**/__pycache__
	rm -f *.db
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "🧹 Cache and .db files removed"
