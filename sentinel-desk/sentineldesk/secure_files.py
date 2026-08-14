"""Owner-only writes for local secret material (OAuth tokens, credential JSON).

The guarantee this module makes is deliberately narrow and *checked*: after
:func:`write_owner_only_text` returns, the file on disk is readable only by the
account that wrote it, and that has been verified by reading the permissions
back. If the restriction cannot be applied or cannot be verified, the file is
deleted and :class:`FileProtectionError` is raised — a token must never be left
lying around world-readable because the hardening step quietly failed.

POSIX and Windows express "owner only" differently, so both mechanisms are
implemented natively rather than pretending POSIX mode bits work on Windows:

* POSIX  — ``0o600`` mode bits, verified with ``stat``.
* Windows — an explicit DACL with inheritance removed and exactly one trustee
  (the current user), applied and verified with ``icacls``. ``os.chmod`` alone
  is not enough: on Windows it only toggles the read-only attribute and leaves
  ``st_mode`` reporting ``0o666``.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")


class FileProtectionError(RuntimeError):
    """Owner-only protection could not be applied or verified."""


@dataclass(frozen=True)
class FileProtection:
    mechanism: str
    detail: str
    owner_only: bool

    def to_dict(self) -> dict[str, object]:
        return {"mechanism": self.mechanism, "detail": self.detail, "owner_only": self.owner_only}


def _current_windows_principal() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    if not user:
        raise FileProtectionError("Cannot determine the current Windows user to grant token access to.")
    return f"{domain}\\{user}" if domain else user


def _run_icacls(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["icacls", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _apply_windows_acl(path: Path) -> FileProtection:
    principal = _current_windows_principal()
    # /inheritance:r drops inherited ACEs, /grant:r replaces rather than adds, so
    # the result is exactly one trustee with full control.
    applied = _run_icacls([str(path), "/inheritance:r", "/grant:r", f"{principal}:(F)"])
    if applied.returncode != 0:
        raise FileProtectionError(
            f"Failed to restrict access on the token file (icacls exit {applied.returncode})."
        )
    return _verify_windows_acl(path, principal)


def _verify_windows_acl(path: Path, principal: str) -> FileProtection:
    listing = _run_icacls([str(path)])
    if listing.returncode != 0:
        raise FileProtectionError("Could not read back the token file ACL to verify it.")
    trustees = _parse_icacls_trustees(listing.stdout, path)
    if not trustees:
        raise FileProtectionError("Token file ACL could not be parsed for verification.")
    # The security property is "exactly one principal can reach this file", so that
    # is what gets checked. The name is compared on its account component only:
    # icacls may resolve the same account as MACHINE\user, DOMAIN\user, or a bare
    # user depending on the host, and a spelling difference is not a leak.
    if len(trustees) > 1:
        raise FileProtectionError(
            f"Token file is still accessible to {len(trustees)} principals after hardening."
        )
    granted = trustees[0].rsplit("\\", 1)[-1].lower()
    expected = principal.rsplit("\\", 1)[-1].lower()
    if granted != expected:
        raise FileProtectionError(
            "Token file's single ACL entry is not the current user; refusing to treat it as protected."
        )
    return FileProtection(
        mechanism="windows_acl",
        detail="owner-only DACL (inheritance removed, single trustee)",
        owner_only=True,
    )


def _parse_icacls_trustees(output: str, path: Path) -> list[str]:
    """Pull the trustee names out of `icacls <file>` output.

    Output looks like::

        C:\\path\\token.json NT-DOMAIN\\user:(F)
                             BUILTIN\\Administrators:(F)

        Successfully processed 1 files; Failed processing 0 files
    """
    trustees: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("successfully processed"):
            continue
        # The first line is prefixed with the file path; strip it off.
        if line.startswith(str(path)):
            line = line[len(str(path)):].strip()
        if not line or ":(" not in line:
            continue
        trustees.append(line.split(":(", 1)[0].strip())
    return trustees


def _apply_posix_mode(path: Path) -> FileProtection:
    os.chmod(path, 0o600)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise FileProtectionError(f"Token file mode is {oct(mode)}, expected 0o600.")
    return FileProtection(mechanism="posix_mode", detail="0o600", owner_only=True)


def protect_owner_only(path: Path) -> FileProtection:
    """Restrict ``path`` to the current owner and verify it. Raises if it cannot."""
    if IS_WINDOWS:
        return _apply_windows_acl(path)
    return _apply_posix_mode(path)


def describe_protection(path: Path) -> FileProtection:
    """Report the current protection of ``path`` without changing it."""
    try:
        if IS_WINDOWS:
            return _verify_windows_acl(path, _current_windows_principal())
        mode = stat.S_IMODE(path.stat().st_mode)
        return FileProtection(
            mechanism="posix_mode",
            detail=oct(mode),
            owner_only=mode == 0o600,
        )
    except FileProtectionError as exc:
        return FileProtection(mechanism="windows_acl" if IS_WINDOWS else "posix_mode", detail=str(exc), owner_only=False)


def write_owner_only_text(path: Path, text: str) -> FileProtection:
    """Write ``text`` to ``path`` so only the current owner can read it.

    Fails closed: if the restriction cannot be applied or verified, the partially
    written file is removed and :class:`FileProtectionError` is raised.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_EXCL-free but mode-carrying open: on POSIX this creates the file already
    # at 0o600 so it is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    try:
        return protect_owner_only(path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
