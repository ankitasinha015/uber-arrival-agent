"""Web layer — a consumer of the core agent, not an adapter of it.

This package wraps the LangGraph adapter in a FastAPI app and streams the
agent's decisions to the browser over Server-Sent Events. It lives at the top
level of the package (not under adapters/) on purpose: it USES an ArrivalAgent,
it does not IMPLEMENT one. See DESIGN.md decision D4.
"""
