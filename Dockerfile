# One image runs the whole app: the React admin is built here and served by
# FastAPI, so `docker compose up` gives you everything at :8820 -- no separate
# frontend process. AI still runs on edge-ai (Ollama), not in this container.

# --- stage 1: build the React admin -------------------------------------
FROM node:20-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build          # -> /ui/dist

# --- stage 2: the python app --------------------------------------------
FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# The built SPA; app/main.py mounts ./frontend/dist at / when present.
COPY --from=ui /ui/dist ./frontend/dist

EXPOSE 8820
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8820"]
