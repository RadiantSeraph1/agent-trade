FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY web ./web
RUN pip install ".[api,cloud]"
RUN useradd -m app && chown -R app /app
USER app
ENV PORT=8080 FXLAB_WEB_DIR=/app/web
CMD ["sh", "-c", "uvicorn fxlab.api.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
