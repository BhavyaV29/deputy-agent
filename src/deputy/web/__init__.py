"""Deputy's local web UI: chat, a live SSE action stream, approvals, and audit.

Everything is served from within the package and bound to loopback only. The
:func:`create_app` factory takes an :class:`~deputy.web.service.AgentService`, so
the routes are agnostic to how the agent is assembled — production wires the real
model and tools, tests wire a scripted fake.
"""

from __future__ import annotations

from deputy.web.server import create_app

__all__ = ["create_app"]
