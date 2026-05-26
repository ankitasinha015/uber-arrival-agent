"""Per-run metrics collection.

The framework comparison (step 7, `--compare`) needs tool-call counts, LLM-call
counts, token usage, and runtime per adapter run. Rather than bolt that on later
at every call site, we instrument at the tool layer here: each tool is wrapped
with `@instrumented`, and an active `Metrics` collector (set per run via a
contextvar) records the call. If no collector is active (e.g. a plain unit test),
recording is a no-op — zero overhead, no required wiring.

contextvar (not a global): each adapter run sets its own collector, so parallel
or nested runs don't clobber each other's counts.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, TypeVar


@dataclass
class Metrics:
    """Counters for one agent run."""

    tool_calls: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_breakdown: dict[str, int] = field(default_factory=dict)
    _start: float = field(default_factory=time.monotonic)

    def record_tool(self, name: str) -> None:
        self.tool_calls += 1
        self.tool_breakdown[name] = self.tool_breakdown.get(name, 0) + 1

    def record_llm(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.llm_calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    @property
    def runtime_s(self) -> float:
        return round(time.monotonic() - self._start, 3)

    def as_dict(self) -> dict:
        return {
            "tool_calls": self.tool_calls,
            "llm_calls": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tool_breakdown": dict(self.tool_breakdown),
            "runtime_s": self.runtime_s,
        }


_current: ContextVar[Metrics | None] = ContextVar("arrival_agent_metrics", default=None)


def start_run() -> Metrics:
    """Begin a fresh metrics collection for this run. Returns the collector."""
    m = Metrics()
    _current.set(m)
    return m


def current() -> Metrics | None:
    """The active collector, or None if metrics aren't being collected."""
    return _current.get()


F = TypeVar("F", bound=Callable)


def instrumented(tool_name: str) -> Callable[[F], F]:
    """Decorator: record a tool call against the active collector (if any)."""

    def decorate(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            m = _current.get()
            if m is not None:
                m.record_tool(tool_name)
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
