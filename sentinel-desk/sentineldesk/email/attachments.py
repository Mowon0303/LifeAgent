from __future__ import annotations

import html
import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TEXT_SUFFIXES = {".txt", ".md", ".csv", ".tsv", ".json", ".ics", ".log"}
HTML_SUFFIXES = {".html", ".htm"}


@dataclass(frozen=True)
class ParsedAttachment:
    name: str
    text: str
    content_type: str
    warnings: tuple[str, ...] = ()


def parse_attachment_file(path: str | Path, *, base_dir: str | Path | None = None) -> ParsedAttachment:
    source = Path(path)
    if not source.is_absolute() and base_dir is not None:
        source = Path(base_dir) / source
    suffix = source.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return ParsedAttachment(source.name, _read_text(source), f"text/{suffix.lstrip('.') or 'plain'}")
    if suffix in HTML_SUFFIXES:
        text = _html_to_text(_read_text(source))
        return ParsedAttachment(source.name, text, "text/html")
    if suffix == ".pdf":
        return _parse_pdf(source)
    return ParsedAttachment(source.name, "", "application/octet-stream", ("unsupported_attachment_type",))


def parse_attachment_files(paths: list[str] | tuple[str, ...], *, base_dir: str | Path | None = None) -> list[ParsedAttachment]:
    return [parse_attachment_file(path, base_dir=base_dir) for path in paths]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _parse_pdf(path: Path) -> ParsedAttachment:
    parser = _load_pdf_parser()
    if parser is None:
        return ParsedAttachment(path.name, "", "application/pdf", ("pdf_parser_unavailable",))
    try:
        reader = parser(str(path))
        pages = getattr(reader, "pages", [])
        text = "\n".join((page.extract_text() or "") for page in pages)
    except Exception:
        return ParsedAttachment(path.name, "", "application/pdf", ("pdf_parse_failed",))
    return ParsedAttachment(path.name, text, "application/pdf")


def _load_pdf_parser() -> Any | None:
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        reader = getattr(module, "PdfReader", None)
        if reader is not None:
            return reader
    return None
