# Stage 1: Frontend build
FROM node:20-alpine AS frontend-build

WORKDIR /app/src/viewer
COPY src/viewer/package.json src/viewer/package-lock.json* ./
RUN npm ci
COPY src/viewer/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    colmap \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

COPY --from=frontend-build /app/src/viewer/dist ./src/viewer/dist

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
