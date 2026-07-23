# Backend image: FastAPI + the research agent. AI runs on edge-ai (Ollama), not
# here -- this container only orchestrates and stores. The React SPA runs on the
# Vite dev server (`make ui`); bake it in later for single-container prod.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

EXPOSE 8820
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8820"]
