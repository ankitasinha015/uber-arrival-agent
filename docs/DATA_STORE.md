# Synthetic data store — ChromaDB

Real trip/user data isn't available, so the web demo runs on **synthetic data seeded
into ChromaDB** and reads from it at runtime — the same shape a real backend would
have. The only thing that stays a live external call is the **restaurant geo**
(Foursquare); everything about the traveler comes from the data store.

## What's in Chroma

Two collections (`src/arrival_agent/web/chroma_store.py`):

| Collection | Rows | Used for |
|---|---|---|
| `travelers` | one per traveler | the login roster + every trip fact (flight, city, hotel, delay, bookings) — stored as metadata, loaded back into the app's traveler shape |
| `eats_orders` | many per traveler | synthetic **Uber Eats order history** (embedded dish + cuisine). The dinner **taste ranking is derived from here** — aggregate the cuisines a traveler orders most — not a hardcoded list. This is the first-party-data "moat", data-driven. |

Embeddings are computed **locally** from the cached `all-MiniLM-L6-v2` model
(`HF_HUB_OFFLINE=1`) and passed to Chroma; the container only stores/searches them.

## Why Docker

ChromaDB's native Rust backend **segfaults** on this Windows + Anaconda machine (and
the pre-Rust 0.5.x won't compile without a C++ toolchain). So Chroma runs in a
**container** and the app talks to it over HTTP — the Rust core runs in the container,
the Python side only makes network calls, so there's no crash.

```bash
docker run -d --name chroma -p 8001:8000 chromadb/chroma
```

## Running the app on Chroma

```bash
# 1. start Chroma (once)
docker run -d --name chroma -p 8001:8000 chromadb/chroma

# 2. run the web server with the Chroma flag + offline model
CONCIERGE_CHROMA=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python -m uvicorn arrival_agent.web.server:app --port 8077
```

On startup the server seeds the synthetic data into Chroma (wipe + reseed, so edits
to the seed always propagate) and then reads travelers back from it.

**Fallback:** without `CONCIERGE_CHROMA=1` (tests, or Chroma down), the app uses the
in-code synthetic seed directly — nothing hard-depends on a running container. `CHROMA_HOST`
/ `CHROMA_PORT` override the connection (default `localhost:8001`).
