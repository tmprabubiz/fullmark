"""
fullmark/utils/file_utils.py
----------------------------
File type detection and ZIP unpacking utilities.
"""

from __future__ import annotations

import mimetypes
import zipfile
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Extension routing table
# ──────────────────────────────────────────────────────────────────────────────

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".doc", ".rtf", ".txt",
    ".epub", ".xlsx", ".xls", ".csv", ".ods",
    ".pptx", ".ppt", ".odp", ".ipynb", ".msg", ".eml",
})

IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp",
    ".tiff", ".tif", ".webp", ".svg",
})

VIDEO_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".m4a",
})

WEB_EXTENSIONS: frozenset[str] = frozenset({
    ".html", ".htm",
})

ARCHIVE_EXTENSIONS: frozenset[str] = frozenset({
    ".zip",
})


def detect_agent(source: str | Path) -> str:
    """
    Determine which agent should handle *source*.

    Args:
        source: File path (str or Path) or URL string.

    Returns:
        One of: ``"web"``, ``"document"``, ``"image"``, ``"video"``,
        ``"archive"``, or ``"unknown"``.
    """
    source_str = str(source)

    # URL → Web Agent
    if source_str.startswith(("http://", "https://")):
        return "web"

    path = Path(source_str)
    ext = path.suffix.lower()

    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in WEB_EXTENSIONS:
        return "web"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"

    # MIME fallback
    mime, _ = mimetypes.guess_type(source_str)
    if mime:
        if mime.startswith("image/"):
            return "image"
        if mime.startswith("video/") or mime.startswith("audio/"):
            return "video"
        if mime in ("text/html", "application/xhtml+xml"):
            return "web"
        if mime in (
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/csv",
            "text/plain",
        ):
            return "document"

    logger.warning("Cannot detect agent for %r — extension %r not in routing table", source_str, ext)
    return "unknown"


def unpack_zip(zip_path: Path) -> tuple[Path, list[Path]]:
    """
    Extract a ZIP archive to a temporary directory.

    Args:
        zip_path: Path to the ZIP file.

    Returns:
        Tuple of (temp_dir_path, list_of_extracted_file_paths).
        Caller is responsible for cleaning up temp_dir_path.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="fullmark_zip_"))
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            # Security: strip path traversal components
            safe_name = Path(member.filename).name
            if not safe_name:
                continue
            dest = temp_dir / member.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
            extracted.append(dest)
            logger.debug("Extracted %s → %s", member.filename, dest)

    logger.info("Unpacked %s: %d files → %s", zip_path.name, len(extracted), temp_dir)
    return temp_dir, extracted


def safe_output_path(source: str | Path, output_dir: Path, suffix: str = ".md") -> Path:
    """
    Compute a safe output path for *source* inside *output_dir*.

    Args:
        source: Original source path or URL.
        output_dir: Directory to write output into.
        suffix: File suffix for output (default ``.md``).

    Returns:
        Resolved output Path.
    """
    source_str = str(source)
    if source_str.startswith(("http://", "https://")):
        # Derive stem from URL
        from urllib.parse import urlparse
        parsed = urlparse(source_str)
        stem = Path(parsed.path).stem or parsed.netloc.replace(".", "_")
    else:
        stem = Path(source_str).stem

    # Sanitise stem — keep alphanumeric, dash, underscore, dot
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
    safe = safe.strip("._") or "output"
    return output_dir / (safe + suffix)
