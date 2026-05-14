"""Demo runner.

Replays a scenario timeline (scenarios/*.json) against a chosen adapter, printing
the agent's decision and reasoning at each event — so you can watch it predict,
wait, re-time, recover, and finally surface a draft order to authorize.

Usage (Implementation: TODO):
    arrival-agent --scenario delayed-flight --adapter langgraph
    arrival-agent --scenario delayed-flight --adapter raw
"""

from __future__ import annotations


def main() -> None:
    """Parse args, load scenario + adapter, replay events, print decisions."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
