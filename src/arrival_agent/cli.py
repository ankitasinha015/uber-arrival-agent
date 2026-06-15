"""Demo runner.

Replays a scenario timeline against a chosen adapter, printing the agent's
decision and reasoning at each event — watch it predict, wait, re-time,
recover, and finally surface a choice set.

Usage:
    arrival-agent --scenario delayed-flight --adapter langgraph
    arrival-agent --scenario repeat-traveler --pick 2

If the scenario contains no user_pick event and the agent is waiting on a
choice when the timeline ends, the runner injects a pick (option N from
--pick, default 1) so the run completes with a placed order — the full loop,
end to end.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from arrival_agent.core import cache, metrics
from arrival_agent.core.contract import Action, AgentDecision
from arrival_agent.core.events import EventType, TripEvent, load_scenario
from arrival_agent.core.tools import flight

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "scenarios"


def _print_decision(ev: TripEvent, d: AgentDecision) -> None:
    stamp = f"{ev.at:%H:%M}"
    print(f"\n[{stamp}] event: {ev.type.value}")
    print(f"  -> {d.action.value.upper()}: {d.reasoning}")
    if d.room_arrival_estimate:
        print(f"     room arrival estimate: {d.room_arrival_estimate:%H:%M}")
    if d.action == Action.SURFACE and d.choice_set:
        if d.axis:
            print(f"     axis: {d.axis.value}")
        for o in d.choice_set:
            total = f"${o.est_total:.0f}" if o.est_total else "—"
            eta = f"{o.est_delivery_at:%H:%M}" if o.est_delivery_at else "—"
            print(f"      [{o.option_id}] {o.restaurant_name} | {', '.join(o.items)} | {total} | eta {eta}")
            print(f"           why: {o.why_this_one}")
        if d.why_these:
            print(f"     why these: {d.why_these}")


def main() -> None:
    p = argparse.ArgumentParser(prog="arrival-agent")
    p.add_argument("--scenario", default="delayed-flight",
                   help="scenario name (in scenarios/) or a path to a JSON file")
    p.add_argument("--adapter", default="langgraph", choices=["langgraph", "raw", "naive"])
    p.add_argument("--pick", type=int, default=1,
                   help="which option to auto-pick when the timeline ends mid-choice (1-based)")
    p.add_argument("--no-taste", action="store_true", help="disable the taste store")
    p.add_argument("--compare", action="store_true",
                   help="run all three adapters on the scenario and print a metrics table")
    args = p.parse_args()

    path = Path(args.scenario)
    if not path.exists():
        path = SCENARIOS_DIR / f"{args.scenario}.json"
    if not path.exists():
        sys.exit(f"scenario not found: {args.scenario}")
    sc = load_scenario(path)

    cache_mode = cache.install()
    if cache_mode != "off":
        print(f"cache: {cache_mode}")

    if args.compare:
        from arrival_agent import compare as compare_mod
        print(compare_mod.compare(sc.name, pick=args.pick))
        return

    _ADAPTERS = {
        "langgraph": ("arrival_agent.adapters.langgraph.graph", "LangGraphArrivalAgent"),
        "raw": ("arrival_agent.adapters.raw.loop", "RawArrivalAgent"),
        "naive": ("arrival_agent.adapters.naive.loop", "NaiveArrivalAgent"),
    }
    import importlib
    mod_path, cls_name = _ADAPTERS[args.adapter]
    AgentCls = getattr(importlib.import_module(mod_path), cls_name)

    taste_store = None
    if not args.no_taste and sc.itinerary.get("past_picks") and cache_mode != "replay":
        from arrival_agent.core.domain.taste import TasteStore
        taste_store = TasteStore(in_memory=True)
        user = taste_store.seed_from_scenario(sc)
        print(f"taste store seeded: {len(sc.itinerary['past_picks'])} past picks for {user!r}")

    flight.set_active_scenario(sc)
    m = metrics.start_run()
    agent = AgentCls(scenario=sc, taste_store=taste_store)

    print(f"=== {sc.name}: {sc.description}")
    last_decision: AgentDecision | None = None
    for ev in sc.events:
        flight.advance_clock(ev.at)
        last_decision = agent.handle_event(ev)
        _print_decision(ev, last_decision)

    if last_decision is not None and last_decision.action == Action.SURFACE and last_decision.choice_set:
        idx = max(1, min(args.pick, len(last_decision.choice_set))) - 1
        chosen = last_decision.choice_set[idx]
        pick = TripEvent(
            type=EventType.USER_PICK,
            at=sc.events[-1].at + timedelta(minutes=2),
            payload={"option_id": chosen.option_id},
        )
        print(f"\n[auto-pick] user picks [{chosen.option_id}] {chosen.restaurant_name}")
        _print_decision(pick, agent.handle_event(pick))

    print(f"\n=== run metrics: {m.as_dict()}")


if __name__ == "__main__":
    main()
