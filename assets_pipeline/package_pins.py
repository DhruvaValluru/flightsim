"""Per-file pins of an aircraft package: git blob sha1 AND sha256.

An aircraft config may list ``package_files``: every file of the upstream
package that the conversion reads beyond the commit pin (textures, the
livery, the interior models, the model XML the offsets were read from).
Each row names the file's git blob sha1 at the pinned commit (what the
GitHub tree API lists, so the inventory and the config can be compared
without a download) and the sha256 of its bytes (what the rest of this
repo pins assets by). Both are checked against the bytes on disk before
anything is converted: a checkout that is not the pinned content refuses
by name (``aircraft.package_pin``), it is never converted "close enough".

Stdlib only; the converter and the importer both call :func:`verify`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Sequence

#: The refusal name (core/messages/catalog.yaml).
PIN_CONSTRAINT = "aircraft.package_pin"

_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
ROW_KEYS = ("file", "git_blob_sha1", "sha256", "bytes", "role")


class PackagePinError(Exception):
    """A pinned package file is missing or is not the pinned content."""

    def __init__(self, message: str, constraint: str = PIN_CONSTRAINT) -> None:
        super().__init__(message)
        self.message = message
        self.constraint = constraint


def git_blob_sha1(data: bytes) -> str:
    """The git object id of a blob with these bytes (``git hash-object``)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pin_row(path: Path, rel: str, role: str) -> Dict:
    """The ``package_files`` row for a file on disk (used to write pins)."""
    data = Path(path).read_bytes()
    return {"file": rel, "git_blob_sha1": git_blob_sha1(data),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "role": role}


def validate_rows(rows: Sequence[Dict]) -> List[str]:
    """Shape problems of a ``package_files`` list (empty when usable)."""
    problems: List[str] = []
    seen = set()
    for row in rows:
        missing = [k for k in ROW_KEYS if k not in row]
        if missing:
            problems.append(f"{row.get('file')!r} lacks {missing}")
            continue
        if row["file"] in seen:
            problems.append(f"{row['file']!r} is pinned twice")
        seen.add(row["file"])
        if Path(row["file"]).is_absolute() or ".." in Path(row["file"]).parts:
            problems.append(f"{row['file']!r} is not a path inside the package")
        if not _SHA1.fullmatch(str(row["git_blob_sha1"])):
            problems.append(f"{row['file']!r}: git_blob_sha1 is not 40 hex digits")
        if not _SHA256.fullmatch(str(row["sha256"])):
            problems.append(f"{row['file']!r}: sha256 is not 64 hex digits")
        if not isinstance(row["bytes"], int) or row["bytes"] < 0:
            problems.append(f"{row['file']!r}: bytes must be a non-negative integer")
        if not str(row["role"]).strip():
            problems.append(f"{row['file']!r}: role is empty")
    return problems


def verify(config: Dict, source_dir: Path) -> List[Dict]:
    """Check every ``package_files`` row against ``source_dir``. Returns
    the verified rows (for the manifest); raises :class:`PackagePinError`
    naming every file that is missing or differs. A config without
    ``package_files`` verifies nothing and returns []."""
    rows = config.get("package_files") or []
    problems = validate_rows(rows)
    if problems:
        raise PackagePinError("package_files is malformed: " + "; ".join(problems),
                              constraint="aircraft.package_pin")
    bad: List[str] = []
    for row in rows:
        path = Path(source_dir) / row["file"]
        if not path.is_file():
            bad.append(f"{row['file']} is missing")
            continue
        data = path.read_bytes()
        if len(data) != row["bytes"]:
            bad.append(f"{row['file']} is {len(data)} bytes, pinned {row['bytes']}")
        elif git_blob_sha1(data) != row["git_blob_sha1"]:
            bad.append(f"{row['file']} git blob {git_blob_sha1(data)[:12]}, "
                       f"pinned {row['git_blob_sha1'][:12]}")
        elif hashlib.sha256(data).hexdigest() != row["sha256"]:
            bad.append(f"{row['file']} sha256 differs from the pin")
    if bad:
        raise PackagePinError(
            f"{len(bad)} pinned package file(s) are not the pinned content in "
            f"{source_dir}: " + "; ".join(bad), constraint="aircraft.package_pin")
    return [dict(row) for row in rows]


def pinned(config: Dict, rel: str) -> bool:
    """Whether ``rel`` (a package path) is one of the config's pins."""
    return any(row.get("file") == rel for row in config.get("package_files") or [])
