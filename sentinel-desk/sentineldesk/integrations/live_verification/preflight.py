"""The live verification preflight, as Python instead of Bash.

This used to be ``scripts/live_verification_preflight.sh``, which meant Windows
users could not run the one workflow that gates a real Gmail rollout. The plan
now lives here and the shell script is a thin wrapper, so both platforms execute
the *same* sequence, approval gate, and exit codes.

Safety properties preserved from the shell version:

* every step is echoed before it runs (``+ ...``), and in dry-run mode only echoed;
* echoed lines are redacted, so a token in the environment never reaches stdout;
* external calendar writes are refused unless explicitly approved;
* a refused approval exits 2, a failing step exits with its own code.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence, TextIO

from sentineldesk.redact import redact

APPROVAL_REFUSED_EXIT_CODE = 2
NO_RUNTIME_EXIT_CODE = 2


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default) == "1"


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class PreflightConfig:
    root: Path
    home: Path
    python_bin: str
    account: str
    gmail_query: str = "deadline OR due"
    google_credentials_env: str = "SENTINEL_GOOGLE_CREDENTIALS_JSON"
    google_token_env: str = "SENTINEL_GOOGLE_TOKEN_JSON"
    apple_user_env: str = "SENTINEL_APPLE_ID"
    apple_password_env: str = "SENTINEL_APPLE_APP_PASSWORD"
    google_calendar_id: str = "primary"
    apple_calendar_id: str = "default"
    google_confirmation_id: str = "live-google-sandbox-001"
    apple_confirmation_id: str = "live-apple-sandbox-001"
    dry_run: bool = True
    run_google_token: bool = False
    google_token_no_browser: bool = False
    run_gmail_sync: bool = False
    seed_calendar_draft: bool = False
    run_calendar_writes: bool = False
    run_release_package: bool = True
    approved: bool = False
    require_ready: bool = False
    release_output: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "sentineldesk.release.zip")
    release_extract_dir: Path | None = None

    @classmethod
    def from_environment(cls, *, root: Path | None = None) -> "PreflightConfig":
        project_root = (root or Path(__file__).resolve().parents[3]).resolve()
        default_release = Path(tempfile.gettempdir()) / "sentineldesk.release.zip"
        extract_dir = os.environ.get("SENTINEL_LIVE_RELEASE_EXTRACT_DIR") or ""
        return cls(
            root=project_root,
            home=Path(_env("SENTINEL_LIVE_HOME", str(project_root / ".demo"))),
            python_bin=_env("SENTINEL_LIVE_PYTHON", sys.executable),
            account=_env("SENTINEL_LIVE_ACCOUNT", "user@example.com"),
            gmail_query=_env("SENTINEL_LIVE_GMAIL_QUERY", "deadline OR due"),
            google_credentials_env=_env("SENTINEL_LIVE_GOOGLE_CREDENTIALS_ENV", "SENTINEL_GOOGLE_CREDENTIALS_JSON"),
            google_token_env=_env("SENTINEL_LIVE_GOOGLE_TOKEN_ENV", "SENTINEL_GOOGLE_TOKEN_JSON"),
            apple_user_env=_env("SENTINEL_LIVE_APPLE_USER_ENV", "SENTINEL_APPLE_ID"),
            apple_password_env=_env("SENTINEL_LIVE_APPLE_PASSWORD_ENV", "SENTINEL_APPLE_APP_PASSWORD"),
            google_calendar_id=_env("SENTINEL_LIVE_GOOGLE_CALENDAR_ID", "primary"),
            apple_calendar_id=_env("SENTINEL_LIVE_APPLE_CALENDAR_ID", "default"),
            google_confirmation_id=_env("SENTINEL_LIVE_GOOGLE_CONFIRMATION_ID", "live-google-sandbox-001"),
            apple_confirmation_id=_env("SENTINEL_LIVE_APPLE_CONFIRMATION_ID", "live-apple-sandbox-001"),
            dry_run=_flag("SENTINEL_LIVE_DRY_RUN"),
            run_google_token=_flag("SENTINEL_LIVE_RUN_GOOGLE_TOKEN"),
            google_token_no_browser=_flag("SENTINEL_LIVE_GOOGLE_TOKEN_NO_BROWSER"),
            run_gmail_sync=_flag("SENTINEL_LIVE_RUN_GMAIL_SYNC"),
            seed_calendar_draft=_flag("SENTINEL_LIVE_SEED_CALENDAR_DRAFT"),
            run_calendar_writes=_flag("SENTINEL_LIVE_RUN_CALENDAR_WRITES"),
            run_release_package=_flag("SENTINEL_LIVE_RUN_RELEASE_PACKAGE", default="1"),
            approved=_flag("SENTINEL_LIVE_APPROVED"),
            require_ready=_flag("SENTINEL_LIVE_REQUIRE_READY"),
            release_output=Path(_env("SENTINEL_LIVE_RELEASE_OUTPUT", str(default_release))),
            release_extract_dir=Path(extract_dir) if extract_dir else None,
        )

    def base_cmd(self) -> list[str]:
        return [self.python_bin, "-B", "-m", "sentineldesk", "--home", str(self.home)]


def _secret_values() -> list[str]:
    """Concrete secret values present in this environment, to scrub from output."""
    values: list[str] = []
    for name, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        upper = name.upper()
        if any(token in upper for token in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY")):
            values.append(value)
    return sorted(values, key=len, reverse=True)


class _Printer:
    """Everything the preflight prints goes through here, already redacted.

    Values are redacted **individually**, before they are joined into a line. That
    matters for paths containing spaces: `C:\\Users\\Jane Doe\\My Home` is
    unambiguously a path when it arrives as one argv element, but once it has been
    concatenated into a command line no pattern can tell where it ends and the next
    argument begins. Redacting per value removes the guesswork entirely.
    """

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._secrets = _secret_values()

    def _scrub(self, text: str) -> str:
        safe = str(text)
        for secret in self._secrets:
            safe = safe.replace(secret, "[REDACTED_SECRET]")
        return safe

    def value(self, text: object) -> str:
        """Redact a single value (an argv element, a path, an account)."""
        return redact(self._scrub(str(text)))

    def line(self, text: str = "") -> None:
        self.stream.write(redact(self._scrub(text)) + "\n")
        self.stream.flush()

    def field(self, label: str, value: object) -> None:
        self.stream.write(f"{label}: {self.value(value)}\n")
        self.stream.flush()

    def command(self, argv: Sequence[object], *, prefix: str = "+") -> None:
        rendered = " ".join(self.value(item) for item in argv)
        self.stream.write(f"{prefix} {rendered}\n")
        self.stream.flush()


Runner = Callable[[Sequence[str]], int]


def _default_runner(argv: Sequence[str]) -> int:
    return subprocess.run(list(argv), check=False).returncode


def run_preflight(
    config: PreflightConfig,
    *,
    stream: TextIO | None = None,
    runner: Runner | None = None,
) -> int:
    out = _Printer(stream if stream is not None else sys.stdout)
    execute = runner or _default_runner
    base = config.base_cmd()

    def run(argv: Sequence[str]) -> int:
        out.command(argv)
        if config.dry_run:
            return 0
        return execute(argv)

    out.line("LifeAgent live verification preflight")
    out.field("Platform", sys.platform)
    out.field("Home", config.home)
    out.field("Account", config.account)
    out.field("Dry run", int(config.dry_run))
    out.field("Seed local verification calendar draft", int(config.seed_calendar_draft))
    out.field("External calendar writes enabled", int(config.run_calendar_writes))
    out.field("Source release package audit enabled", int(config.run_release_package))
    out.field("Final require-ready gate", int(config.require_ready))

    if not config.dry_run and not Path(config.python_bin).exists() and config.python_bin != sys.executable:
        out.field("No executable Python runtime found (set SENTINEL_LIVE_PYTHON)", config.python_bin)
        return NO_RUNTIME_EXIT_CODE

    code = run([*base, "integrations", "env-template",
                "--account", config.account,
                "--google-credentials-env", config.google_credentials_env,
                "--google-token-env", config.google_token_env,
                "--apple-user-env", config.apple_user_env,
                "--apple-password-env", config.apple_password_env])
    if code:
        return code

    if config.run_google_token:
        token_cmd = [*base, "integrations", "google-token",
                     "--credentials-env", config.google_credentials_env,
                     "--token-env", config.google_token_env]
        if config.google_token_no_browser:
            token_cmd.append("--no-browser")
        code = run(token_cmd)
        if code:
            return code
        token_file = config.home / "secrets" / "google-token.json"
        if not config.dry_run and token_file.exists():
            os.environ[config.google_token_env] = token_file.read_text(encoding="utf-8")
            out.line(f"Loaded Google token JSON from the local token file into {config.google_token_env} for this run.")
    else:
        out.line("Skipping Google OAuth token flow. Set SENTINEL_LIVE_RUN_GOOGLE_TOKEN=1 to run it.")

    check_args = ["integrations", "check", "--suite", "all",
                  "--account", config.account,
                  "--google-credentials-env", config.google_credentials_env,
                  "--google-token-env", config.google_token_env,
                  "--apple-user-env", config.apple_user_env,
                  "--apple-password-env", config.apple_password_env,
                  "--package"]
    code = run([*base, *check_args])
    if code:
        return code

    if config.run_gmail_sync:
        code = run([*base, "email", "sync-gmail",
                    "--account", config.account,
                    "--query", config.gmail_query,
                    "--credentials-env", config.google_credentials_env,
                    "--token-env", config.google_token_env])
        if code:
            return code
    else:
        out.line("Skipping Gmail sync. Set SENTINEL_LIVE_RUN_GMAIL_SYNC=1 after approving Gmail readonly access.")

    if config.seed_calendar_draft:
        code = run([*base, "integrations", "seed-calendar-draft"])
        if code:
            return code
    else:
        out.line(
            "Skipping local verification calendar draft seed. "
            "Set SENTINEL_LIVE_SEED_CALENDAR_DRAFT=1 if Gmail sync produced no deadline draft."
        )

    if config.run_calendar_writes:
        # The approval gate is unconditional: it applies in dry-run too, so a
        # misconfigured run fails here rather than at the moment of the write.
        if not config.approved:
            out.line("Refusing external calendar writes without SENTINEL_LIVE_APPROVED=1.")
            return APPROVAL_REFUSED_EXIT_CODE
        for argv in _calendar_write_commands(config, base):
            code = run(argv)
            if code:
                return code
    else:
        out.line(
            "Skipping external calendar writes. Set SENTINEL_LIVE_RUN_CALENDAR_WRITES=1 "
            "and SENTINEL_LIVE_APPROVED=1 after reviewing draft events."
        )

    final_check = [*base, *check_args]
    if config.require_ready:
        final_check.append("--require-ready")
    code = run(final_check)
    if code:
        return code

    source_release_path = config.release_extract_dir or Path(tempfile.gettempdir()) / "extracted-sentineldesk"
    if config.run_release_package:
        code, source_release_path = _release_package_steps(config, base, run, out, source_release_path)
        if code:
            return code
    else:
        out.line("Skipping source release package audit. Set SENTINEL_LIVE_RUN_RELEASE_PACKAGE=1 to run it.")

    audit_cmd = [*base, "integrations", "completion-audit",
                 "--account", config.account,
                 "--google-credentials-env", config.google_credentials_env,
                 "--google-token-env", config.google_token_env,
                 "--apple-user-env", config.apple_user_env,
                 "--apple-password-env", config.apple_password_env,
                 "--source-release-path", str(source_release_path)]
    if config.require_ready:
        audit_cmd.append("--require-ready")
    code = run(audit_cmd)
    if code:
        return code

    privacy_cmd = [*base, "privacy", "audit"]
    if config.require_ready:
        privacy_cmd.append("--require-clean")
    code = run(privacy_cmd)
    if code:
        return code

    out.line(
        "Live verification preflight finished. Use the latest redacted integration package "
        "and clean source release package after the privacy audits pass."
    )
    return 0


def _calendar_write_commands(config: PreflightConfig, base: list[str]) -> list[list[str]]:
    return [
        [*base, "calendar", "sync", "--destination", "google",
         "--account", config.account, "--calendar-id", config.google_calendar_id],
        [*base, "calendar", "sync", "--destination", "google",
         "--account", config.account, "--calendar-id", config.google_calendar_id,
         "--confirm", "--confirmation-id", config.google_confirmation_id,
         "--google-credentials-env", config.google_credentials_env,
         "--google-token-env", config.google_token_env],
        [*base, "calendar", "sync", "--destination", "apple",
         "--account", config.account, "--calendar-id", config.apple_calendar_id],
        [*base, "calendar", "sync", "--destination", "apple",
         "--account", config.account, "--calendar-id", config.apple_calendar_id,
         "--confirm", "--confirmation-id", config.apple_confirmation_id,
         "--apple-user-env", config.apple_user_env,
         "--apple-password-env", config.apple_password_env],
    ]


def _release_package_steps(
    config: PreflightConfig,
    base: list[str],
    run: Callable[[Sequence[str]], int],
    out: _Printer,
    source_release_path: Path,
) -> tuple[int, Path]:
    package_cmd = [*base, "privacy", "release-package", "--source", str(config.root), "--output", str(config.release_output)]
    if config.dry_run:
        run(package_cmd)
        out.command(["mkdir", "-p", source_release_path])
        out.command([config.python_bin, "-B", "-m", "zipfile", "-e", config.release_output, source_release_path])
        run([*base, "privacy", "release-audit", "--path", str(source_release_path), "--require-clean"])
        return 0, source_release_path

    if config.release_extract_dir is None:
        source_release_path = Path(tempfile.mkdtemp(prefix="sentineldesk-release-audit."))
    else:
        source_release_path = config.release_extract_dir
        source_release_path.mkdir(parents=True, exist_ok=True)

    code = run(package_cmd)
    if code:
        return code, source_release_path
    # Extract in-process instead of shelling out to `python -m zipfile`, which
    # keeps this identical on Windows and POSIX.
    out.command(["extract", config.release_output, "->", source_release_path])
    with zipfile.ZipFile(config.release_output) as archive:
        archive.extractall(source_release_path)
    code = run([*base, "privacy", "release-audit", "--path", str(source_release_path), "--require-clean"])
    return code, source_release_path


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point behind ``sentineldesk integrations preflight``."""
    return run_preflight(PreflightConfig.from_environment())
