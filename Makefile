.PHONY: install install-backend install-frontend dev dev-backend dev-frontend \
        test test-backend test-frontend migrate migrate-create lint backup restore

install: install-backend install-frontend

install-backend:
	cd backend && python -m venv venv && . venv/bin/activate && \
	python -m pip install -r requirements-dev.txt -c constraints-tested-win-py314.txt

install-frontend:
	cd frontend && npm ci

dev-backend:
	cd backend && . venv/bin/activate && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make dev-backend' and 'make dev-frontend' in two separate terminals."

test: test-backend test-frontend

test-backend:
	cd backend && . venv/bin/activate && pytest

migrate:
	cd backend && . venv/bin/activate && alembic upgrade head

migrate-create:
	cd backend && . venv/bin/activate && alembic revision --autogenerate -m "$(msg)"

# Include migrations alongside application code and tests because they are executable Python code.
lint:
	cd backend && . venv/bin/activate && black app tests migrations && isort app tests migrations && ruff check app tests migrations
	cd frontend && npm run lint

test-frontend:
	cd frontend && npm test

backup:
	cd backend && . venv/bin/activate && python -m app.cli.backup

restore:
	cd backend && . venv/bin/activate && python -m app.cli.restore "$(filename)" \
	--expected-sha256 "$(sha256)" --confirmation "RESTORE $(filename)" \
	$(if $(request_id),--request-id "$(request_id)",)
