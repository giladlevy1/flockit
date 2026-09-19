.PHONY: help up down demo dev-db dev-server dev-web test test-collector test-server test-web collector lint clean

DEV_DB_URL ?= postgresql+asyncpg://flockit:flockit@localhost:55432/flockit

help:
	@echo "make up              start Flockit with docker compose (http://localhost:8080)"
	@echo "make demo            load demo data into a fresh compose deployment"
	@echo "make down            stop it"
	@echo ""
	@echo "make dev-db          start a local Postgres for development (port 55432)"
	@echo "make dev-server      run the API with reload on :8080"
	@echo "make dev-web         run the UI with hot reload on :5173 (proxies the API)"
	@echo "make test            run every test suite"

up:
	docker compose up -d --build
	@echo "Flockit is starting at http://localhost:$${FLOCKIT_PORT:-8080}"

demo:
	docker compose run --rm flockit flockit-server seed-demo

down:
	docker compose down

dev-db:
	docker run -d --name flockit-devdb -e POSTGRES_USER=flockit -e POSTGRES_PASSWORD=flockit \
		-e POSTGRES_DB=flockit -p 55432:5432 postgres:16-alpine

server/.venv:
	cd server && uv venv -q --python 3.12 .venv && uv pip install -q --python .venv/bin/python -e ".[dev]"

collector/.venv:
	cd collector && uv venv -q --python 3.12 .venv && uv pip install -q --python .venv/bin/python -e ".[dev]"

web/node_modules:
	cd web && npm ci

collector: collector/.venv
	cd collector && uv build --wheel -q -o dist

dev-server: server/.venv collector
	cd server && FLOCKIT_DATABASE_URL=$(DEV_DB_URL) FLOCKIT_COLLECTOR_DIST=../collector/dist \
		FLOCKIT_WEB_DIST=../web/dist .venv/bin/flockit-server migrate && \
		FLOCKIT_DATABASE_URL=$(DEV_DB_URL) FLOCKIT_COLLECTOR_DIST=../collector/dist FLOCKIT_WEB_DIST=../web/dist \
		.venv/bin/uvicorn flockit_server.main:app --reload --port 8080

dev-web: web/node_modules
	cd web && npm run dev

test: test-collector test-server test-web

test-collector: collector/.venv
	cd collector && .venv/bin/pytest -q

test-server: server/.venv
	cd server && FLOCKIT_TEST_DATABASE_URL=$${FLOCKIT_TEST_DATABASE_URL:-postgresql+asyncpg://flockit:flockit@localhost:55432/flockit_test} .venv/bin/pytest -q

test-web: web/node_modules
	cd web && npm run build

lint: collector/.venv server/.venv
	collector/.venv/bin/ruff check collector
	server/.venv/bin/ruff check server

clean:
	rm -rf collector/dist web/dist collector/.venv server/.venv web/node_modules
