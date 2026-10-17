# Convenience targets for local development (see README).
PY := backend/.venv/bin/python

.PHONY: setup migrate seed api web build test test-backend test-frontend e2e screenshots lint

setup:            ## install backend and frontend dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd frontend && npm ci

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
