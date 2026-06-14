"""Tool-first agent answering.

Historically a single ``graph.py`` with one large ``answer_question`` dispatcher
plus many per-intent helpers. Now a package: ``answer`` holds the dispatcher and
the per-intent logic lives in ``facts`` / ``general`` / ``portal`` / ``runs`` /
``policy``. The public surface (``answer_question``) is unchanged, so
``from sentineldesk.agent.graph import answer_question`` keeps working.
"""

from __future__ import annotations

from .answer import answer_question

__all__ = ["answer_question"]
