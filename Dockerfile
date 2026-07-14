# Deploy image for the public demo (Hugging Face Spaces / any Docker host).
# Runs LIVE: the concierge makes real Foursquare + Mapbox calls per traveler. Supply
# FOURSQUARE_API_KEY and MAPS_API_KEY as environment secrets. Light by design — the
# [taste] extra (sentence-transformers, torch) is intentionally NOT installed; the
# personas + taste rankings come from the in-code seed, geo is the live call.
FROM python:3.12-slim

WORKDIR /app

# Core deps from pyproject (no [taste] extra).
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# Recorded API + LLM responses for the single-moment arrival agent at "/" (replay).
COPY scenarios ./scenarios

# Run from source so the package's relative paths (static/, scenarios/cache/) resolve
# under /app rather than site-packages.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

# Hugging Face Spaces routes to port 7860 by default (matches app_port in README).
EXPOSE 7860
CMD ["sh", "-c", "python -m uvicorn arrival_agent.web.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
