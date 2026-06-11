from __future__ import annotations

import os
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .redact import EMAIL_RE, PATH_RE, PHONE_RE, URL_RE


ALLOWED_URLS = {
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://caldav.icloud.com",
}
SECRET_VALUE_RE = re.compile(
    r'"(?:access_token|api_key|app_password|authorization|client_secret|cookie|credentials|id_token|password|refresh_token|secret|token|token_json)"\s*:\s*"(?!(?:\[REDACTED_SECRET\]|env:[^"]+:\*\*\*))[^\"]+"',
    re.IGNORECASE,
)
RELEASE_BLOCKED_DIR_NAMES = {
    ".agent-venv",
    ".demo",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".sentineldesk",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "chrome-profile",
    "dist",
    "dom_dumps",
    "node_modules",
    "recordings",
    "screenshots",
    "secrets",
    "traces",
    "venv",
}
RELEASE_BLOCKED_DIR_SUFFIXES = (".egg-info",)
RELEASE_BLOCKED_FILE_NAMES = {".DS_Store"}
RELEASE_BLOCKED_FILE_SUFFIX_KINDS = {
    ".db": "local_database",
    ".evidence.json": "evidence_artifact",
    ".env": "env_file",
    ".log": "log_artifact",
    ".mov": "recording_artifact",
    ".mp4": "recording_artifact",
    ".png": "image_or_screenshot_artifact",
    ".pyc": "bytecode_file",
    ".pyo": "bytecode_file",
    ".redacted.json": "redacted_artifact",
    ".report.html": "report_artifact",
    ".share.zip": "share_package",
    ".sqlite": "local_database",
    ".sqlite3": "local_database",
    ".trace.jsonl": "trace_artifact",
}


@dataclass(frozen=True)
class PrivacyIssue:
    artifact: str
    member: str
    kind: str
    marker: str
    detail: str


def audit_redacted_artifacts(root: Path) -> dict[str, object]:
    root = root.resolve()
    issues: list[PrivacyIssue] = []
    scanned: list[str] = []
    for path in _candidate_files(root):
        rel = _relative(path, root)
        if path.suffix == ".zip":
            scanned.append(rel)
            issues.extend(_scan_zip(path, root))
            continue
        scanned.append(rel)
        issues.extend(_scan_text(path.read_text(encoding="utf-8", errors="replace"), artifact=rel, member=""))
    return {
        "status": "clean" if not issues else "leaks_found",
        "root": "[REDACTED_PATH]" if root.is_absolute() else str(root),
        "scanned_count": len(scanned),
        "scanned_files": scanned,
        "issue_count": len(issues),
        "issues": [asdict(issue) for issue in issues],
        "privacy": "Scans redacted JSON, redacted HTML reports, and .share.zip package text. Raw evidence files are intentionally excluded.",
    }


def audit_project_tree(root: Path) -> dict[str, object]:
    root = root.resolve()
    issues: list[PrivacyIssue] = []
    scanned_files = 0
    scanned_dirs = 0
    if not root.exists():
        return {
            "status": "missing_root",
            "root": "[REDACTED_PATH]" if root.is_absolute() else str(root),
            "scanned_files": 0,
            "scanned_dirs": 0,
            "issue_count": 1,
            "issues": [
                asdict(
                    PrivacyIssue(
                        artifact=root.name or ".",
                        member="",
                        kind="missing_root",
                        marker="[MISSING_ROOT]",
                        detail="Project release audit root does not exist.",
                    )
                )
            ],
            "privacy": "Scans project-tree filenames for local runtime artifacts and generated caches without reading file contents.",
        }
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        if ".git" in current_path.parts:
            dirnames[:] = []
            continue
        scanned_dirs += 1
        keep_dirs: list[str] = []
        for dirname in sorted(dirnames):
            path = current_path / dirname
            issue = _release_dir_issue(path, root)
            if issue:
                issues.append(issue)
                continue
            keep_dirs.append(dirname)
        dirnames[:] = keep_dirs
        for filename in sorted(filenames):
            scanned_files += 1
            issue = _release_file_issue(current_path / filename, root)
            if issue:
                issues.append(issue)
    issues = _dedupe_issues(issues)
    return {
        "status": "clean" if not issues else "artifacts_found",
        "root": "[REDACTED_PATH]" if root.is_absolute() else str(root),
        "scanned_files": scanned_files,
        "scanned_dirs": scanned_dirs,
        "issue_count": len(issues),
        "issues": [asdict(issue) for issue in sorted(issues, key=lambda item: (item.artifact, item.kind))],
        "privacy": "Scans project-tree filenames for local runtime artifacts and generated caches without reading file contents.",
    }


def write_release_package(source: Path, output_path: Path) -> dict[str, object]:
    source = source.resolve()
    output_path = output_path.resolve()
    excluded: list[PrivacyIssue] = []
    included: list[str] = []
    if not source.exists():
        return {
            "status": "missing_source",
            "source": "[REDACTED_PATH]" if source.is_absolute() else str(source),
            "package_path": str(output_path),
            "file_count": 0,
            "excluded_count": 1,
            "excluded": [
                asdict(
                    PrivacyIssue(
                        artifact=source.name or ".",
                        member="",
                        kind="missing_root",
                        marker="[MISSING_ROOT]",
                        detail="Release package source does not exist.",
                    )
                )
            ],
        }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for current, dirnames, filenames in os.walk(source):
            current_path = Path(current)
            if ".git" in current_path.parts:
                dirnames[:] = []
                continue
            keep_dirs: list[str] = []
            for dirname in sorted(dirnames):
                path = current_path / dirname
                issue = _release_dir_issue(path, source)
                if issue:
                    excluded.append(issue)
                    continue
                keep_dirs.append(dirname)
            dirnames[:] = keep_dirs
            for filename in sorted(filenames):
                path = current_path / filename
                if path.resolve() == output_path:
                    excluded.append(
                        PrivacyIssue(
                            artifact=_relative(path, source),
                            member="",
                            kind="release_package",
                            marker="[LOCAL_ARTIFACT]",
                            detail="Release package output is excluded from itself.",
                        )
                    )
                    continue
                issue = _release_file_issue(path, source)
                if issue:
                    excluded.append(issue)
                    continue
                rel = _relative(path, source)
                archive.write(path, rel)
                included.append(rel)
    excluded = _dedupe_issues(excluded)
    return {
        "status": "written",
        "source": "[REDACTED_PATH]" if source.is_absolute() else str(source),
        "package_path": str(output_path),
        "file_count": len(included),
        "excluded_count": len(excluded),
        "excluded": [asdict(issue) for issue in sorted(excluded, key=lambda item: (item.artifact, item.kind))],
        "privacy": "Writes a source release ZIP while excluding the same local runtime artifacts flagged by privacy release-audit.",
    }


def _release_dir_issue(path: Path, root: Path) -> PrivacyIssue | None:
    name = path.name
    if name not in RELEASE_BLOCKED_DIR_NAMES and not name.endswith(RELEASE_BLOCKED_DIR_SUFFIXES):
        return None
    return PrivacyIssue(
        artifact=_relative(path, root),
        member="",
        kind="runtime_directory",
        marker="[LOCAL_ARTIFACT]",
        detail="Local runtime, dependency, cache, or build directory should not be included in a public release.",
    )


def _release_file_issue(path: Path, root: Path) -> PrivacyIssue | None:
    name = path.name
    if name in RELEASE_BLOCKED_FILE_NAMES:
        return PrivacyIssue(
            artifact=_relative(path, root),
            member="",
            kind="metadata_file",
            marker="[LOCAL_ARTIFACT]",
            detail="Local metadata file should not be included in a public release.",
        )
    for suffix, kind in RELEASE_BLOCKED_FILE_SUFFIX_KINDS.items():
        if name.endswith(suffix):
            return PrivacyIssue(
                artifact=_relative(path, root),
                member="",
                kind=kind,
                marker="[LOCAL_ARTIFACT]",
                detail="Generated runtime artifact should not be included in a public release.",
            )
    return None


def _candidate_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".share.zip") or name.endswith(".redacted.json") or name.endswith(".report.html"):
            candidates.append(path)
    return sorted(candidates)


def _scan_zip(path: Path, root: Path) -> list[PrivacyIssue]:
    issues: list[PrivacyIssue] = []
    artifact = _relative(path, root)
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                try:
                    text = archive.read(member).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                issues.extend(_scan_text(text, artifact=artifact, member=member))
    except zipfile.BadZipFile:
        issues.append(
            PrivacyIssue(
                artifact=artifact,
                member="",
                kind="invalid_zip",
                marker="[INVALID_ZIP]",
                detail="Package could not be opened as a ZIP file.",
            )
        )
    return issues


def _scan_text(text: str, *, artifact: str, member: str) -> list[PrivacyIssue]:
    issues: list[PrivacyIssue] = []
    issues.extend(_regex_issues(text, EMAIL_RE, artifact, member, "email", "[REDACTED_EMAIL]", "Raw email address found."))
    issues.extend(_regex_issues(text, PHONE_RE, artifact, member, "phone", "[REDACTED_PHONE]", "Raw phone number found."))
    issues.extend(_regex_issues(text, PATH_RE, artifact, member, "local_path", "[REDACTED_PATH]", "Local filesystem path found."))
    for match in URL_RE.finditer(text):
        if match.group(0) in ALLOWED_URLS:
            continue
        issues.append(
            PrivacyIssue(
                artifact=artifact,
                member=member,
                kind="url",
                marker="[REDACTED_URL]",
                detail="Raw URL found.",
            )
        )
    for _ in SECRET_VALUE_RE.finditer(text):
        issues.append(
            PrivacyIssue(
                artifact=artifact,
                member=member,
                kind="secret_value",
                marker="[REDACTED_SECRET]",
                detail="Secret-like JSON value found.",
            )
        )
    return _dedupe_issues(issues)


def _regex_issues(text: str, pattern: re.Pattern[str], artifact: str, member: str, kind: str, marker: str, detail: str) -> list[PrivacyIssue]:
    return [
        PrivacyIssue(
            artifact=artifact,
            member=member,
            kind=kind,
            marker=marker,
            detail=detail,
        )
        for _ in pattern.finditer(text)
    ]


def _dedupe_issues(issues: list[PrivacyIssue]) -> list[PrivacyIssue]:
    unique: dict[tuple[str, str, str], PrivacyIssue] = {}
    for issue in issues:
        unique.setdefault((issue.artifact, issue.member, issue.kind), issue)
    return list(unique.values())


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return path.name
