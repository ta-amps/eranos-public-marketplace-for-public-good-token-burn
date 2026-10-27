# Build from the workspace root so both tessera and eranos are in the build context.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY eranos /app/eranos
WORKDIR /app/eranos
RUN uv sync --frozen --no-dev
ENV PATH="/app/eranos/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "eranos.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
