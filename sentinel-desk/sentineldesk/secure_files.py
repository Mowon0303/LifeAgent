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
* Windows — inheritance removed and an explicit DACL granting the current user,
  applied and verified with ``icacls``. ``os.chmod`` alone is not enough: on
  Windows it only toggles the read-only attribute and leaves ``st_mode``
  reporting ``0o666``.

What "owner only" means on Windows deserves stating plainly, because the obvious
stricter rule is wrong. ``0o600`` on POSIX does not exclude root, and a Windows
DACL cannot exclude LocalSystem or the Administrators group either — a member of
either can take ownership and rewrite the ACL at will. So the property actually
verified here is: **no principal beyond the file's owner and the built-in
privileged accounts may reach the file.** A DACL that still grants Authenticated
Users, Users, or Everyone fails that check and fails closed.

Verification reads the DACL back as SDDL, which identifies trustees by SID.
Parsing ``icacls``'s human-readable names instead would break on any non-English
Windows, where ``BUILTIN\\Administrators`` is printed in the local language.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

# SDDL trustees that Windows always effectively grants, expressed both as the
# two-letter aliases SDDL uses and as the raw SIDs, since either spelling can
# appear: LocalSystem, the Administrators group, the local Administrator
# account, and Owner Rights (which is the owner — us).
PRIVILEGED_TRUSTEES = {
    "SY", "S-1-5-18",
    "BA", "S-1-5-32-544",
    "LA",
    "OW", "S-1-3-4",
}
# (A;flags;rights;objectguid;inheritobjectguid;trustee)
_ACE_RE = re.compile(r"\((?P<type>[A-Z]*);(?P<flags>[A-Z]*);[^;]*;[^;]*;[^;]*;(?P<trustee>[^)]+)\)")

# SDDL prints well-known trustees as two-letter aliases, but icacls /remove wants
# something it can resolve. Mapping back to the SID keeps the removal
# locale-independent; anything already in S-1-… form is used as-is.
_ALIAS_TO_SID = {
    "AU": "S-1-5-11",    # Authenticated Users
    "BU": "S-1-5-32-545",  # Users
    "WD": "S-1-1-0",     # Everyone
    "IU": "S-1-5-4",     # Interactive
    "NU": "S-1-5-2",     # Network
    "PU": "S-1-5-32-547",  # Power Users
    "BG": "S-1-5-32-546",  # Guests
    "AN": "S-1-5-7",     # Anonymous
}


class FileProtectionError(RuntimeError):
    """Owner-only protection could not be applied or verified."""


@dataclass(frozen=True)
class FileProtection:
    mechanism: str
    detail: str
    owner_only: bool

    def to_dict(self) -> dict[str, object]:
        return {"mechanism": self.mechanism, "detail": self.detail, "owner_only": self.owner_only}


def _current_user_sid() -> str:
    """The current account's SID.

    Granting by SID rather than by ``DOMAIN\\user`` avoids depending on name
    resolution, which varies with domain membership and machine naming.
    """
    result = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise FileProtectionError("Cannot determine the current Windows account SID.")
    fields = [field.strip().strip('"') for field in result.stdout.strip().split(",")]
    sid = fields[-1] if fields else ""
    if not sid.startswith("S-1-"):
        raise FileProtectionError("Could not parse the current Windows account SID.")
    return sid


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
    sid = _current_user_sid()
    # /inheritance:r drops inherited ACEs; /grant:r replaces this trustee's entry
    # rather than adding to it.
    applied = _run_icacls([str(path), "/inheritance:r", "/grant:r", f"*{sid}:(F)"])
    if applied.returncode != 0:
        raise FileProtectionError(
            f"Failed to restrict access on the token file (icacls exit {applied.returncode})."
        )

    # /inheritance:r removes only *inherited* entries. An explicit ACE for another
    # principal survives it, and an existing file being rewritten keeps whatever
    # DACL it already had — so anything still granting access outside the owner and
    # the built-in privileged accounts has to be removed by name.
    for trustee in sorted(_granted_trustees(path) - {sid} - PRIVILEGED_TRUSTEES):
        target = _ALIAS_TO_SID.get(trustee, trustee)
        prefix = "*" if target.startswith("S-1-") else ""
        _run_icacls([str(path), "/remove:g", f"{prefix}{target}"])

    return _verify_windows_acl(path, sid)


def _verify_windows_acl(path: Path, sid: str) -> FileProtection:
    granted = _granted_trustees(path)
    if not granted:
        raise FileProtectionError("Token file ACL could not be read back for verification.")
    if sid not in granted:
        raise FileProtectionError(
            "Token file does not grant the current account; refusing to treat it as protected."
        )
    outsiders = sorted(granted - {sid} - PRIVILEGED_TRUSTEES)
    if outsiders:
        # Authenticated Users, Users, Everyone, or another account: the token
        # really would be readable by someone else, so fail closed and say who.
        raise FileProtectionError(
            "Token file is still readable by non-privileged principals after hardening: "
            + ", ".join(outsiders)
        )
    privileged = sorted(granted & PRIVILEGED_TRUSTEES)
    detail = "owner-only DACL (inheritance removed)"
    if privileged:
        # Stated rather than hidden: these cannot be excluded on Windows, in the
        # same way 0o600 does not exclude root.
        detail += "; built-in privileged accounts retain access: " + ", ".join(privileged)
    return FileProtection(mechanism="windows_acl", detail=detail, owner_only=True)


def _granted_trustees(path: Path) -> set[str]:
    """Trustees with an effective allow ACE on ``path``, as SDDL SIDs/aliases."""
    sddl = _file_sddl(path)
    if not sddl:
        return set()
    trustees: set[str] = set()
    for match in _ACE_RE.finditer(sddl):
        if "A" not in match.group("type"):
            continue  # deny ACEs restrict access, they do not grant it
        if "IO" in match.group("flags"):
            continue  # inherit-only: applies to children, not this file
        trustees.add(match.group("trustee").strip())
    return trustees


def _file_sddl(path: Path) -> str:
    """Read ``path``'s DACL as SDDL via ``icacls /save``.

    ``/save`` operates on a directory and writes ``name``/``SDDL`` line pairs for
    its entries, as UTF-16. The save file is written outside the scanned
    directory so it cannot appear in its own listing.
    """
    handle, save_name = tempfile.mkstemp(prefix="sentineldesk-acl-", suffix=".sddl")
    os.close(handle)
    save_path = Path(save_name)
    try:
        result = _run_icacls([str(path.parent), "/save", str(save_path), "/T", "/Q", "/C"])
        if result.returncode != 0 and not save_path.exists():
            return ""
        raw = save_path.read_bytes()
    finally:
        save_path.unlink(missing_ok=True)

    for encoding in ("utf-16", "utf-16-le", "utf-8"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if "\x00" in text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for name, sddl in zip(lines, lines[1:]):
            if not sddl.startswith(("D:", "O:", "G:")):
                continue
            if Path(name).name.lower() == path.name.lower():
                return sddl
    return ""


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
            return _verify_windows_acl(path, _current_user_sid())
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
