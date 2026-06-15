# Deploy image for the public demo. Runs in cache REPLAY mode: no API keys, no
# outbound calls, no taste store / torch. Light by design.
FROM python:3.12-slim

WORKDIR /app

# Install core deps from pyproject (the [taste] extra — sentence-transformers,
# torch — is intentionally NOT installed; replay never touches the taste store).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Recorded API + LLM responses live here; replay serves from them.
COPY scenarios ./scenarios

# Run from source so the package's relative paths (static/, scenarios/cache/)
# resolve under /app rather than site-packages.
ENV ARRIVAL_AGENT_CACHE=replay \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["sh", "-c", "python -m uvicorn arrival_agent.web.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
