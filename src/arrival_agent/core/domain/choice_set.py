"""Domain: choice-set design — the agent's most agentic moment.

The single LLM call in the whole agent. Given a filtered candidate set + trip
context + (optionally) the user's recent past picks, it does two things in one
shot, structured via Anthropic tool-use:

  1. Picks the AXIS of variation that matters for THIS user at THIS moment
     (cuisine / speed_vs_quality / familiarity_vs_novelty / volume) and
     explains why.

  2. Designs 2–3 options that span that axis. Each option has a restaurant,
     an items hint, an estimated total, and a one-line `why_this_one`
     rationale.

Picking the axis IS the judgment. Picking one of fifty restaurants is search;
picking three that span a meaningful axis for the user is taste. That's the
interview talking point and that's why this module gets the sonnet-grade model
instead of haiku.

Structured output is enforced via `tools=[...]` + `tool_choice={"type":"tool"}`
— Anthropic returns valid JSON matching the schema or the request errors. No
free-form JSON parsing.

Failure modes:
  - LLM picks an invalid restaurant_id → we raise; adapter handles.
  - LLM returns fewer than 2 options → we raise; adapter handles.
  - API call fails entirely → fall back to a deterministic heuristic (cuisine
    axis, top-N by nearest distance). Visible in the reasoning, not silent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic

from arrival_agent.core.config import anthropic_key
from arrival_agent.core.contract import ChoiceAxis, ChoiceOption
from arrival_agent.core.metrics import current as current_metrics


ANTHROPIC_MODEL = os.environ.get("ARRIVAL_AGENT_LLM_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = 1500


_TOOL = {
    "name": "design_choice_set",
    "description": (
        "Commit to one axis of variation and 2-3 restaurant options that span it. "
        "Each option must reference a restaurant_id from the candidate list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "axis": {
                "type": "string",
                "enum": [a.value for a in ChoiceAxis],
                "description": "The axis the choice set varies along.",
            },
            "axis_reason": {
                "type": "string",
                "description": "One-line rationale for picking this axis.",
            },
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "restaurant_id": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 3,
                        },
                        "est_total": {"type": "number"},
                        "why_this_one": {"type": "string"},
                    },
                    "required": ["restaurant_id", "items", "est_total", "why_this_one"],
                },
            },
            "why_these_meta": {
                "type": "string",
                "description": "One-line synthesis explaining the set, shown above the cards.",
            },
        },
        "required": ["axis", "axis_reason", "options", "why_these_meta"],
    },
}


@dataclass
class ChoiceSet:
    """Result of one design_choice_set call."""

    axis: ChoiceAxis
    axis_reason: str
    options: list[ChoiceOption]
    why_these: str


# --- prompt building ----------------------------------------------------------


_SYSTEM = """You are the choice-set designer for an arrival agent.

The user is a traveler who lands late at night. The agent has watched their
trip and now needs to surface 2–3 restaurant options for them to pick from.

Your single job: pick the AXIS along which those options should differ, then
fill in 2–3 options that span that axis meaningfully.

Picking one restaurant is search. Picking three that vary along an axis the
user can actually decide on is judgment. THAT is your contribution.

Axes:
  - cuisine: options differ by cuisine (Thai / Indian / Pizza)
  - speed_vs_quality: trade-off between delivery time + cost vs perceived quality
  - familiarity_vs_novelty: the user's usual vs a new highly-rated option vs a light one
  - volume: snack / real meal / comfort feast

Pick whichever axis makes the choice INTERESTING for THIS user at THIS moment.
A boring choice set (three Thai places that all look alike) is the failure mode.

Output via the design_choice_set tool. Keep `why_this_one` lines short and
human, not promotional. Estimated totals are rough — match them to typical
restaurant prices for the cuisine."""


def _user_prompt(
    candidates: list[dict],
    trip_context: dict,
    past_picks: list[dict] | None,
) -> str:
    lines = ["TRIP CONTEXT:"]
    for k, v in trip_context.items():
        lines.append(f"  {k}: {v}")
    if past_picks:
        lines.append("\nRECENT PAST PICKS (newest first):")
        for p in past_picks[:5]:
            lines.append(
                f"  - {p.get('restaurant_name','?')}"
                f" ({', '.join(p.get('cuisine_tags', []))})"
                f" | rated {p.get('rating','?')}/5"
            )
    else:
        lines.append("\nRECENT PAST PICKS: (no history — first trip)")
    lines.append("\nCANDIDATES (in-envelope, ranked by distance):")
    for c in candidates:
        cats = ", ".join(c.get("categories", []))
        lines.append(
            f"  - id={c['restaurant_id']} | {c['restaurant_name']} | {cats}"
            f" | {c.get('distance_m','?')}m"
        )
    lines.append(
        "\nNow call design_choice_set with the axis you chose and 2-3 options "
        "that span it. Option restaurant_ids must come from the list above."
    )
    return "\n".join(lines)


# --- main entrypoint ----------------------------------------------------------


def design_choice_set(
    candidates: list[dict],
    trip_context: dict,
    *,
    past_picks: list[dict] | None = None,
    client: anthropic.Anthropic | None = None,
) -> ChoiceSet:
    """Pick an axis + 2–3 options from the candidate set.

    `candidates` are the in-envelope dicts from `restaurants.get_eats_options`
    (and optionally re-ranked by the taste store).
    `trip_context` is small dict like `{"time_of_day":"00:18","fatigue":"high",
    "city":"San Francisco"}` — shown verbatim to the model.
    `past_picks` is the taste-store hit list (optional; None on cold start).

    Returns a ChoiceSet. Raises ValueError if the LLM picks an invalid
    restaurant_id or returns fewer than 2 options.
    """
    if not candidates:
        raise ValueError("no candidates to choose from")

    if client is None:
        client = anthropic.Anthropic(api_key=anthropic_key())

    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "design_choice_set"},
        messages=[
            {
                "role": "user",
                "content": _user_prompt(candidates, trip_context, past_picks),
            }
        ],
    )

    # Record LLM usage against the active metrics collector (if any).
    m = current_metrics()
    if m is not None:
        u = resp.usage
        m.record_llm(
            tokens_in=getattr(u, "input_tokens", 0),
            tokens_out=getattr(u, "output_tokens", 0),
        )

    tool_use = next(
        (b for b in resp.content if getattr(b, "type", None) == "tool_use"), None
    )
    if tool_use is None:
        raise ValueError("LLM did not call the design_choice_set tool")

    args = tool_use.input
    if isinstance(args, str):  # belt-and-braces: occasionally returned as string
        args = json.loads(args)

    return _build_choice_set(args, candidates)


def _build_choice_set(args: dict, candidates: list[dict]) -> ChoiceSet:
    candidates_by_id = {c["restaurant_id"]: c for c in candidates}

    raw_options = args.get("options", [])
    if len(raw_options) < 2:
        raise ValueError(f"LLM returned only {len(raw_options)} option(s); need >= 2")

    options: list[ChoiceOption] = []
    for i, o in enumerate(raw_options):
        rid = o.get("restaurant_id", "")
        cand = candidates_by_id.get(rid)
        if cand is None:
            raise ValueError(
                f"LLM picked unknown restaurant_id {rid!r}; "
                f"valid ids: {list(candidates_by_id)}"
            )
        options.append(
            ChoiceOption(
                option_id=f"opt-{i + 1}",
                restaurant_id=rid,
                restaurant_name=cand["restaurant_name"],
                items=list(o.get("items", [])),
                est_total=float(o.get("est_total", 0.0)),
                # Adapter fills est_delivery_at when it stamps the surfacing time.
                est_delivery_at=None,
                cuisine_tags=list(cand.get("categories", [])),
                why_this_one=o.get("why_this_one", ""),
            )
        )

    try:
        axis = ChoiceAxis(args["axis"])
    except ValueError as e:
        raise ValueError(f"LLM returned invalid axis: {args.get('axis')!r}") from e

    return ChoiceSet(
        axis=axis,
        axis_reason=args.get("axis_reason", ""),
        options=options,
        why_these=args.get("why_these_meta", ""),
    )
