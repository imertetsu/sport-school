# Makefile — atajos del stack LatinoSport.
# Uso: `make up`, `make down`, `make migrate`, etc.

COMPOSE := docker compose -f infra/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help up down migrate seed logs test test-backend test-frontend fmt config

help: ## Lista los targets disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

up: ## Levanta el stack (build + detached)
	$(COMPOSE) up -d --build

down: ## Detiene el stack y elimina contenedores
	$(COMPOSE) down

config: ## Valida el docker-compose.yml
	$(COMPOSE) config

migrate: ## Aplica migraciones (alembic upgrade head) en el contenedor api
	$(COMPOSE) run --rm -e RUN_MIGRATIONS=1 api alembic -c /app/alembic.ini upgrade head

seed: ## Carga datos de ejemplo (python -m app.seed) en el contenedor api
	$(COMPOSE) run --rm api python -m app.seed

logs: ## Sigue los logs de todos los servicios
	$(COMPOSE) logs -f

test: test-backend test-frontend ## Corre tests de backend y frontend

test-backend: ## Tests del backend (pytest)
	cd backend && pytest -q

test-frontend: ## Tests del frontend (vitest)
	cd frontend && npm run test

fmt: ## Formatea backend (ruff) y frontend (eslint --fix)
	cd backend && ruff format . && ruff check --fix .
	cd frontend && npm run lint -- --fix
