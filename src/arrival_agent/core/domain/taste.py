"""Domain: per-user taste store.

The agent gets meaningfully better as it sees more of a user's trips. With
zero history, ranking candidates by Foursquare category overlap is fine but
coarse. Once a user has 50+ past picks, tag overlap breaks down — "user likes
brothy noodles but not stir-fries, even though both are tagged Thai" —
embeddings capture that distinction.

Architecture: an in-process vector store. Documents = past picks as text
("<name> | <cuisines> | <items>") embedded with sentence-transformers
(`all-MiniLM-L6-v2`, local, no API key). Similarity = cosine. Persistence =
pickle (one file per user). For one user at portfolio scale, a managed vector
DB would be overhead; the math is ~80 lines.

(We evaluated `chromadb`. Its 1.x Rust backend crashes on `_add`/`_upsert`
under our Windows test environment — Anaconda Python + Norton AV — with a
process-level access violation. Older versions need a C++ compiler we don't
have for the hnswlib build. For this scale, a direct cosine-similarity store
is simpler and reliable everywhere. See docs/framework-comparison.md.)

Read path: `rank_candidates(user_id, candidates)` — embed each candidate,
compare against the user's well-rated past picks (rating >= 4), sort
candidates ascending by *distance* to nearest match. Cold-start (no history)
returns the input unchanged.

The envelope filter runs FIRST (`envelope.filter_candidates`) — the taste
store re-ranks within the filtered set, never expands beyond it.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_PERSIST_DIR = ".taste"
WELL_RATED_THRESHOLD = 4


@lru_cache
def _model() -> SentenceTransformer:
    """Module-level cache: the model loads once per process (slow ~3s first
    time on cache miss, fast afterward)."""
    return SentenceTransformer(EMBEDDING_MODEL)


def _embed(text: str) -> np.ndarray:
    """Embed a single string; L2-normalize so cosine sim becomes a dot product."""
    vec = _model().encode([text], show_progress_bar=False, normalize_embeddings=True)
    return np.asarray(vec[0], dtype=np.float32)


def _candidate_document(candidate: dict) -> str:
    name = candidate.get("restaurant_name", "")
    cats = " ".join(candidate.get("categories", []))
    items = " ".join(candidate.get("items", []))
    return " | ".join(p for p in (name, cats, items) if p)


def _pick_document(pick: dict) -> str:
    name = pick.get("restaurant_name", "")
    cats = " ".join(pick.get("cuisine_tags", []) or pick.get("categories", []))
    items = " ".join(pick.get("items_ordered", []) or pick.get("items", []))
    return " | ".join(p for p in (name, cats, items) if p)


def _pick_id(user_id: str, pick: dict) -> str:
    """Deterministic id for a pick — re-seeding stays idempotent."""
    name = pick.get("restaurant_name", "unknown")
    ts = pick.get("timestamp", "")
    return f"{user_id}::{name}::{ts}".replace(" ", "_")


@dataclass
class _Row:
    id: str
    document: str
    embedding: np.ndarray
    metadata: dict[str, Any]


@dataclass
class _UserStore:
    rows: list[_Row] = field(default_factory=list)

    def upsert(self, row: _Row) -> None:
        for i, r in enumerate(self.rows):
            if r.id == row.id:
                self.rows[i] = row
                return
        self.rows.append(row)


class TasteStore:
    """Per-user vector store with cosine-similarity ranking."""

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        *,
        in_memory: bool = False,
    ):
        self._in_memory = in_memory
        self._persist_dir = (
            None if in_memory else Path(persist_dir or DEFAULT_PERSIST_DIR).expanduser()
        )
        self._stores: dict[str, _UserStore] = {}
        if self._persist_dir is not None:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._load_all()

    # --- persistence ------------------------------------------------------

    def _user_path(self, user_id: str) -> Path:
        assert self._persist_dir is not None
        return self._persist_dir / f"user_{user_id}.pkl"

    def _load_all(self) -> None:
        assert self._persist_dir is not None
        for path in self._persist_dir.glob("user_*.pkl"):
            user_id = path.stem.replace("user_", "", 1)
            try:
                with open(path, "rb") as f:
                    self._stores[user_id] = pickle.load(f)
            except Exception:
                self._stores[user_id] = _UserStore()

    def _persist(self, user_id: str) -> None:
        if self._in_memory or self._persist_dir is None:
            return
        with open(self._user_path(user_id), "wb") as f:
            pickle.dump(self._stores[user_id], f)

    # --- helpers ----------------------------------------------------------

    def _user(self, user_id: str) -> _UserStore:
        return self._stores.setdefault(user_id, _UserStore())

    @staticmethod
    def _metadata_for(pick: dict) -> dict[str, Any]:
        ts = pick.get("timestamp")
        if isinstance(ts, datetime):
            ts = ts.astimezone(timezone.utc).isoformat()
        return {
            "restaurant_name": pick.get("restaurant_name", ""),
            "rating": int(pick.get("rating", 0)),
            "city": pick.get("city", ""),
            "cuisine_tags": pick.get("cuisine_tags", []),
            "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        }

    # --- write path -------------------------------------------------------

    def record_pick(self, user_id: str, pick: dict) -> None:
        self.record_picks(user_id, [pick])

    def record_picks(self, user_id: str, picks: list[dict]) -> None:
        if not picks:
            return
        u = self._user(user_id)
        for pick in picks:
            doc = _pick_document(pick)
            if not doc:
                continue
            row = _Row(
                id=_pick_id(user_id, pick),
                document=doc,
                embedding=_embed(doc),
                metadata=self._metadata_for(pick),
            )
            u.upsert(row)
        self._persist(user_id)

    # --- read path --------------------------------------------------------

    def has_history(self, user_id: str) -> bool:
        return len(self._user(user_id).rows) > 0

    def recent_picks(self, user_id: str, k: int = 5) -> list[dict]:
        u = self._user(user_id)
        if not u.rows:
            return []
        rows = [
            {
                "restaurant_name": r.metadata.get("restaurant_name", ""),
                "cuisine_tags": list(r.metadata.get("cuisine_tags", [])),
                "rating": int(r.metadata.get("rating", 0)),
                "city": r.metadata.get("city", ""),
                "timestamp": r.metadata.get("timestamp", ""),
                "document": r.document,
            }
            for r in u.rows
        ]
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        return rows[:k]

    def rank_candidates(
        self,
        user_id: str,
        candidates: list[dict],
        *,
        well_rated_threshold: int = WELL_RATED_THRESHOLD,
    ) -> list[dict]:
        """Re-rank candidates by cosine similarity to nearest well-rated past
        pick. Cold-start (no positive history) returns input unchanged."""
        if not candidates:
            return candidates
        u = self._user(user_id)
        if not u.rows:
            return candidates

        well_rated = [r for r in u.rows if r.metadata.get("rating", 0) >= well_rated_threshold]
        if not well_rated:
            return candidates

        # Stack well-rated embeddings into one matrix; vectors are normalized,
        # so a dot product gives cosine similarity directly.
        matrix = np.stack([r.embedding for r in well_rated])  # (k, d)

        scored: list[tuple[float, int, dict]] = []
        for i, cand in enumerate(candidates):
            doc = _candidate_document(cand)
            if not doc:
                scored.append((-float("inf"), i, cand))
                continue
            q = _embed(doc)
            sims = matrix @ q  # (k,) cosine similarities
            scored.append((float(sims.max()), i, cand))

        # Sort by (similarity desc, original_index asc) — closer wins; ties
        # keep the original order (which is geographic distance for Foursquare).
        scored.sort(key=lambda t: (-t[0], t[1]))
        return [c for _, _, c in scored]

    # --- scenario seeding -------------------------------------------------

    def seed_from_scenario(self, scenario) -> str | None:
        user_id = scenario.itinerary.get("user_id")
        picks = scenario.itinerary.get("past_picks") or []
        if not user_id or not picks:
            return None
        self.record_picks(user_id, picks)
        return user_id
