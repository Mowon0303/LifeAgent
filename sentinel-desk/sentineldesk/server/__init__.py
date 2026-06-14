"""Local dashboard HTTP server (standard-library ``http.server``, no framework).

Historically a single ``server.py`` with two large ``do_GET`` / ``do_POST``
methods. Now a package: ``app`` holds the thin request handler + route table,
and the ``handlers_*`` modules hold the per-domain endpoint logic. The public
surface (``Handler``, ``serve``) is unchanged, so ``from sentineldesk.server
import Handler`` keeps working.
"""

from __future__ import annotations

from .app import GET_ROUTES, POST_ROUTES, Handler, Route, serve

__all__ = ["Handler", "serve", "Route", "GET_ROUTES", "POST_ROUTES"]
