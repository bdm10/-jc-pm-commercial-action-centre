# Convenience targets for local development (see README).
# Python used to create the virtualenv (3.12+). On macOS the default python3 may be Apple's 3.9:
#   make setup PYTHON=python3.13
PYTHON ?= python3

.PHONY: setup migrate seed api web build preview test test-backend test-frontend e2e screenshots lint

setup:            ## install backend and frontend dependencies
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required, found " + sys.version.split()[0] + ". Try: make setup PYTHON=python3.13")'
	cd backend && $(PYTHON) -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm ci

preview: migrate seed build   ## one step: schema, fresh synthetic demo data, UI build, then serve on http://localhost:8000
	cd backend && .venv/bin/uvicorn app.main:app --port 8000

migrate:          ## apply database migrations
	cd backend && .venv/bin/python -m app.cli migrate

seed:             ## reset and load the synthetic demo (users, data, opportunities, sample history)
	cd backend && .venv/bin/python -m app.cli seed-demo

api:              ## run the API (and the built SPA, if present) on :8000
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web:              ## run the Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

build:            ## build the SPA into frontend/dist (served by the API)
	cd frontend && npm run build

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/python -m pytest -q

test-frontend:
	cd frontend && npx tsc --noEmit -p tsconfig.json && npm test

e2e:              ## requires the API running on :8000 with the built SPA
	cd frontend && npm run e2e -- e2e/journeys.spec.ts

screenshots:      ## requires the API running on :8000 with the built SPA
	cd frontend && npm run screenshots

lint:
	cd backend && .venv/bin/ruff check app tests
