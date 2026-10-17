# Single deployable image: FastAPI API + built React SPA.
# Used by the hosted demo (render.yaml) and suitable for any container host.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser
EXPOSE 8000
# Checks configuration (fails closed), runs migrations, keeps demo data fresh (APP_ENV=demo), then serves on $PORT.
CMD ["python", "-m", "app.cli", "serve"]
