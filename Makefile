# fleemarket-ai -- niche research + storefront management.
# AI runs on the edge-ai box (Ollama); this app orchestrates + stores.
#
#   make run        build + run EVERYTHING in docker -> http://localhost:8820
#   make logs       tail the docker logs
#   make stop       stop the docker stack
#   make check-llm  confirm the edge-ai connection + list models
#   --- local dev without docker (hot reload, two processes): ---
#   make install    set up the python venv + node deps
#   make dev        backend only (reload) at :8820
#   make ui         React dev server at :5173 (proxies /api to :8820)
PY := .venv/bin/python
PIP := .venv/bin/pip
PORT ?= 8820

install:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt
	cd frontend && npm install

dev:
	.venv/bin/uvicorn backend.main:app --reload --host 0.0.0.0 --port $(PORT)

ui:
	cd frontend && npm run dev

run:
	docker compose up -d --build
	@echo "up -> open http://localhost:$(PORT)  (admin UI + API, all in one container)"

logs:
	docker compose logs -f

stop:
	docker compose down

# Sanity-check the fleet: hit /api/models on a running backend.
check-llm:
	@curl -s http://localhost:$(PORT)/api/models | $(PY) -m json.tool || \
		echo "backend not up? run 'make dev' or 'make run' first"

# Confirm Reddit access (after adding a script app's creds to .env + restart).
check-reddit:
	@curl -s http://localhost:$(PORT)/api/reddit/health | $(PY) -m json.tool || \
		echo "backend not up? run 'make run' first"

# Confirm supply sources for measured saturation (CJ / eBay).
check-saturation:
	@curl -s http://localhost:$(PORT)/api/saturation/health | $(PY) -m json.tool || \
		echo "backend not up? run 'make run' first"

build-ui:
	cd frontend && npm run build

.PHONY: install dev ui run logs stop check-llm check-reddit check-saturation build-ui
