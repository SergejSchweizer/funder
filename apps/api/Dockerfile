FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS runtime

WORKDIR /app
ENV UV_SYSTEM_PYTHON=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system .

RUN useradd --system --create-home --uid 10001 camovar
USER camovar

EXPOSE 8000
CMD ["python", "-m", "camovar.hosted_runtime", "api"]
