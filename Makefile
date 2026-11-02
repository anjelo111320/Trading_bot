.DEFAULT_GOAL := help
.PHONY: help bootstrap check check-backend check-frontend test up down reset migrate api ingestor web openapi types secrets

COMPOSE := docker compose -f infra/docker-compose.yml

help:
	@echo "bootstrap  install everything and create .env"
	@echo "check      lint, type checks, import rules, tests, secret scan"
	@echo "up         start PostgreSQL and Redis"
	@echo "down       stop services, keeping data"
	@echo "reset      stop services and DELETE local data"
	@echo "migrate    apply database migrations"
	@echo "api        run the API"
	@echo "ingestor   run the market-data ingestor"
	@echo "web        run the dashboard"

.env:
	cp .env.example .env
	key=$$(openssl rand -hex 32); perl -pi -e "s/^APP_SECRET_KEY=\$$/APP_SECRET_KEY=$$key/" .env

bootstrap: .env
	cd backend && uv sync
	@if [ -d frontend ]; then cd frontend && pnpm install --frozen-lockfile; fi

check: check-backend check-frontend secrets

check-backend:
	cd backend && uv run ruff format --check .
	cd backend && uv run ruff check .
	cd backend && uv run mypy
	cd backend && uv run lint-imports
	cd backend && uv run pytest

check-frontend:
	@if [ -d frontend ]; then cd frontend && pnpm lint && pnpm typecheck && pnpm test; fi

test:
	cd backend && uv run pytest

secrets:
	gitleaks detect --source . --redact --no-banner

up:
	@docker info >/dev/null 2>&1 || (echo "Docker is not running. Open OrbStack, then run make up again."; exit 1)
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down --volumes

migrate:
	cd backend && uv run alembic upgrade head

api:
	cd backend && uv run python -m trading_intel.entrypoints.api

ingestor:
	cd backend && uv run python -m trading_intel.entrypoints.ingestor

web:
	cd frontend && pnpm dev

openapi:
	cd backend && uv run python -m trading_intel.entrypoints.export_openapi

types: openapi
	cd frontend && pnpm generate:api
