"""Live/sandbox integration readiness verification.

Historically a single ``live_verification.py``; now a package split by concern:
``models`` (result types), ``checks`` (suite/secret/module probes + sandbox
clients), ``runner`` (run + persist a suite), ``completion`` (completion audit +
handoff checklist + action plan), and ``env`` (env-setup template). The public
surface is re-exported here so ``from sentineldesk.integrations.live_verification
import run_verification, build_completion_audit, ...`` keeps working.
"""

from __future__ import annotations

from .completion import build_completion_audit, format_handoff_checklist
from .env import build_env_template
from .models import DEFAULT_SOURCE_RELEASE_PATH, VerificationCheck, VerificationReport
from .runner import run_verification

__all__ = [
    "run_verification",
    "build_completion_audit",
    "format_handoff_checklist",
    "build_env_template",
    "VerificationCheck",
    "VerificationReport",
    "DEFAULT_SOURCE_RELEASE_PATH",
]
