FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS runtime

WORKDIR /app
ENV UV_SYSTEM_PYTHON=1
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system .

RUN useradd --system --create-home --uid 10001 founder
USER founder

EXPOSE 8000
CMD ["python", "-m", "founder.hosted_runtime", "api"]
