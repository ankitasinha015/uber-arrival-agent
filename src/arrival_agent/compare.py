"""Run the same agent on every adapter and emit a side-by-side metrics report.

`arrival-agent --compare --scenario delayed-flight` drives the LangGraph, raw,
and naive adapters through one scenario and prints a markdown table: lines of
code, tool calls, LLM calls, tokens, runtime, and the terminal decision (which
restaurant, timed for when).

The point isn't a winner. It's an honest comparison: LangGraph and the raw loop
produce equivalent decisions (the conformance test proves it) at similar cost —
so the framework's value isn't fewer lines, it's checkpointed state and a real
interrupt. The naive baseline shows what's lost without the agent's judgment:
it orders too early, for the nearest place, with no LLM call.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from arrival_agent.core import metrics
from arrival_agent.core.contract import Action, AgentDecision, ArrivalAgent
from arrival_agent.core.events import EventType, Scenario, TripEvent
from arrival_agent.core.tools import flight

_SRC = Path(__file__).resolve().parent
_ADAPTERS = [
    ("LangGraph", "adapters.langgraph.graph", "LangGraphArrivalAgent",
     _SRC / "adapters" / "langgraph" / "graph.py", True),
    ("raw", "adapters.raw.loop", "RawArrivalAgent",
     _SRC / "adapters" / "raw" / "loop.py", True),
    ("naive", "adapters.naive.loop", "NaiveArrivalAgent",
     _SRC / "adapters" / "naive" / "loop.py", False),
]


def _loc(path: Path) -> int:
    """Lines of code: non-blank lines that aren't pure comments or inside the
    module docstring. Rough but consistent across the three files."""
    n, in_doc = 0, False
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if in_doc:
            if s.endswith('"""') or s.endswith("'''"):
                in_doc = False
            continue
        if s.startswith('"""') or s.startswith("'''"):
            # single-line docstring stays on one line; multi-line opens the block
            if not (len(s) > 3 and (s.endswith('"""') or s.endswith("'''"))):
                in_doc = True
            continue
        if not s or s.startswith("#"):
            continue
        n += 1
    return n


def run_scenario(agent: ArrivalAgent, scenario: Scenario, *, pick: int = 1):
    """Drive a scenario, auto-picking option `pick` the FIRST time the adapter
    surfaces a choice (so the naive baseline — which surfaces early then goes
    quiet — also reaches a placed order). Returns (placed, chosen_option, metrics)."""
    flight.set_active_scenario(scenario)
    m = metrics.start_run()
    placed = None
    chosen = None
    for ev in scenario.events:
        flight.advance_clock(ev.at)
        d = agent.handle_event(ev)
        if placed is None and d.action == Action.SURFACE and d.choice_set:
            idx = max(1, min(pick, len(d.choice_set))) - 1
            chosen = d.choice_set[idx]
            placed = agent.handle_event(TripEvent(
                type=EventType.USER_PICK,
                at=ev.at + timedelta(minutes=2),
                payload={"option_id": chosen.option_id},
            ))
            break
    return placed, chosen, m


def _terminal_summary(chosen) -> str:
    if chosen is None:
        return "—"
    when = f"{chosen.est_delivery_at:%H:%M}" if chosen.est_delivery_at else "?"
    return f"{chosen.restaurant_name} @ {when}"


def compare(scenario_name: str, *, pick: int = 1) -> str:
    import importlib

    from arrival_agent.core.events import load_scenario

    scenarios_dir = _SRC.parents[1] / "scenarios"
    scenario = load_scenario(scenarios_dir / f"{scenario_name}.json")

    rows = []
    for label, mod_path, cls_name, file_path, uses_taste in _ADAPTERS:
        cls = getattr(importlib.import_module(f"arrival_agent.{mod_path}"), cls_name)
        taste = None
        if uses_taste and scenario.itinerary.get("past_picks"):
            from arrival_agent.core.domain.taste import TasteStore
            taste = TasteStore(in_memory=True)
            taste.seed_from_scenario(scenario)
        agent = cls(scenario, taste_store=taste)
        placed, chosen, m = run_scenario(agent, scenario, pick=pick)
        rows.append({
            "label": label,
            "loc": _loc(file_path),
            "tool_calls": m.tool_calls,
            "llm_calls": m.llm_calls,
            "tokens": m.tokens_in + m.tokens_out,
            "runtime_s": m.runtime_s,
            "ordered": _terminal_summary(chosen),
        })

    return _render(scenario_name, rows)


def _render(scenario_name: str, rows: list[dict]) -> str:
    out = [f"## Adapter comparison — `{scenario_name}`", ""]
    out.append("| Adapter | LOC | Tool calls | LLM calls | Tokens | Runtime (s) | Ordered (restaurant @ delivery) |")
    out.append("|---------|-----|-----------|-----------|--------|-------------|---------------------------------|")
    for r in rows:
        out.append(
            f"| {r['label']} | {r['loc']} | {r['tool_calls']} | {r['llm_calls']} "
            f"| {r['tokens']} | {r['runtime_s']} | {r['ordered']} |"
        )
    out.append("")
    return "\n".join(out)
