from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
URL_RE = re.compile(r"(?:https?|file)://[^\s)>\"]+")

# Local paths leak in several shapes, and every one of them has to go:
#
#   C:\Users\name\...                drive letter, backslashes
#   C:/Users/name/...                drive letter, forward slashes (Path.as_posix, JS)
#   D:\CodingProject\...             any drive, not just C:
#   C:\Users\Jane Doe\...            spaces inside a segment
#   C:\Program Files\My App\tool.exe spaces in several segments
#   \\server\share\...               UNC, including a spaced host or share
#   C:\\Users\\name\\...             JSON-escaped form, seen when scanning serialized text
#   /Users/Jane Doe/Documents/...    POSIX home/temp paths, spaces included
#
# Spaces are the hard part: a path segment may contain them, but so may the
# sentence the path sits in. The rule used here is that a *spaced* segment only
# counts as part of the path when another separator follows it — "C:\Program
# Files\My App\tool.exe" is a path all the way to the end, while "save it to
# C:\data and then run" stops at "data" and leaves the prose intact. A trailing
# segment is additionally allowed to keep spaces when it ends in a file
# extension, which covers "...\Jane Doe\my report.pdf".
_SEP = r"(?:\\{1,2}|/)"
_WORD = r"[^\s\\/\"'<>|:*?)\]}]+"
_SPACED = rf"{_WORD}(?:[ ]{_WORD})*"
_TRAILING = rf"{_WORD}(?:[ ]{_WORD})*\.[A-Za-z0-9]{{1,8}}|{_WORD}"

_WINDOWS_DRIVE = rf"(?<![A-Za-z0-9_])[A-Za-z]:{_SEP}(?:{_SPACED}{_SEP})*(?:{_TRAILING})?"
# UNC is backslash-only, so a protocol-relative "//host/path" URL is left to URL_RE.
_WINDOWS_UNC = rf"\\{{2,4}}(?:{_SPACED}\\{{1,2}})+(?:{_TRAILING})?"
WINDOWS_PATH_RE = re.compile(rf"{_WINDOWS_UNC}|{_WINDOWS_DRIVE}")

_POSIX_ROOTS = "Users|home|private|tmp|var|Volumes"
POSIX_PATH_RE = re.compile(
    rf"(?<![A-Za-z0-9_])/(?:{_POSIX_ROOTS})/(?:{_SPACED}/)*(?:{_TRAILING})?"
)

PATH_RE = re.compile(rf"(?:{WINDOWS_PATH_RE.pattern})|(?:{POSIX_PATH_RE.pattern})")

# A value that *is* a local path, rather than a sentence containing one. Dropping
# the whole value sidesteps having to guess where a spaced path ends, which is what
# makes "C:\Users\Jane Doe\My Documents" reliable — the pattern above would stop at
# "My" and leave "Documents" behind.
#
# Deliberate tradeoff: a string that *begins* with an absolute path and then
# continues in prose ("/tmp/foo is missing") is redacted whole. That costs some
# detail in a diagnostic, and the artifacts this runs on are redacted share
# packages, where losing detail is the cheaper mistake than leaking a path. A path
# in the *middle* of a sentence is unaffected and still redacted in place.
WHOLE_PATH_RE = re.compile(
    rf"^\s*[\"']?(?:\\{{2,4}}[^\s\\/]|[A-Za-z]:{_SEP}|/(?:{_POSIX_ROOTS})/)[^\"']*[\"']?\s*$"
)

ID_RE = re.compile(r"\b(?:A-?\d{8,12}|\d{3}-\d{2}-\d{4})\b")

REDACTED_PATH = "[REDACTED_PATH]"


def is_local_path_value(text: str) -> bool:
    """True when the whole string is a local filesystem path, spaces and all."""
    return bool(WHOLE_PATH_RE.match(text))


def redact(text: str) -> str:
    if is_local_path_value(text):
        # The entire value is a path: replace it wholesale rather than trying to
        # find where it ends. This is what makes "C:\Users\Jane Doe\x.json" safe.
        return REDACTED_PATH
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    value = PHONE_RE.sub("[REDACTED_PHONE]", value)
    value = ID_RE.sub("[REDACTED_ID]", value)
    value = URL_RE.sub("[REDACTED_URL]", value)
    value = PATH_RE.sub(REDACTED_PATH, value)
    return value
