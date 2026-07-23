# storefront-ai -- niche research + storefront management.
# AI runs on the edge-ai box (Ollama); this app orchestrates + stores.
#
#   make dev        run the backend locally (reload) against .env
#   make ui         run the React dev server (Vite) at :5173
#   make run        build + start the backend in docker
#   make install    set up the python venv + node deps
#   make check-llm  confirm the edge-ai connection + list models
#   make stop       stop the docker stack
PY := .venv/bin/python
PIP := .venv/bin/pip
PORT ?= 8820

install:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r backend/requirements.txt
	cd frontend && npm install

dev:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(PORT)

ui:
	cd frontend && npm run dev

run:
	docker compose up -d --build
	@echo "backend at http://localhost:$(PORT)  (run 'make ui' for the admin UI)"

stop:
	docker compose down

# Sanity-check the fleet: hit /api/models on a running backend.
check-llm:
	@curl -s http://localhost:$(PORT)/api/models | $(PY) -m json.tool || \
		echo "backend not up? run 'make dev' or 'make run' first"

build-ui:
	cd frontend && npm run build

.PHONY: install dev ui run stop check-llm build-ui
