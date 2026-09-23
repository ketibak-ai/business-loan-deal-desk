FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY knowledge ./knowledge
RUN pip install --upgrade pip && pip install -e .

# Run as non-root
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

# ANTHROPIC_API_KEY (for /api/ask) and APP_API_KEY (to lock the API) are injected at runtime
CMD ["uvicorn", "dealdesk.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
