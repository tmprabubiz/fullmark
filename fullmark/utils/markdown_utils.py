"""
fullmark/utils/markdown_utils.py
---------------------------------
Shared Markdown formatting helpers used by all agents.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path


def front_matter(source: str, agent: str, extra: dict | None = None) -> str:
    """
    Generate YAML front matter for a converted Markdown file.

    Args:
        source: Original source filename or URL.
        agent: Name of the agent that produced this output.
        extra: Optional additional key-value pairs to include.

    Returns:
        YAML front matter block as a string (including ``---`` delimiters).
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"source: {source}",
        f"converted: {now}",
        f"agent: {agent}",
    ]
    if extra:
        for k, v in extra.items():
            # Simple scalar serialisation — no multi-line values
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def image_to_base64(path: Path, mime: str = "image/jpeg") -> str:
    """
    Encode an image file as a base64 data URI for embedding in Markdown.

    Args:
        path: Path to the image file.
        mime: MIME type (default ``image/jpeg``).

    Returns:
        Data URI string: ``data:<mime>;base64,<data>``.
    """
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def bytes_to_base64(data: bytes, mime: str = "image/jpeg") -> str:
    """
    Encode raw bytes as a base64 data URI.

    Args:
        data: Raw bytes.
        mime: MIME type.

    Returns:
        Data URI string.
    """
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def rows_to_gfm_table(headers: list[str], rows: list[list[str]]) -> str:
    """
    Convert a list of rows to a GitHub-Flavoured Markdown pipe table.

    Args:
        headers: Column header strings.
        rows: List of rows; each row is a list of cell strings.

    Returns:
        GFM table string.
    """
    if not headers:
        return ""

    def escape_cell(s: str) -> str:
        return str(s).replace("|", "\\|").replace("\n", " ")

    header_row = "| " + " | ".join(escape_cell(h) for h in headers) + " |"
    separator  = "| " + " | ".join("---" for _ in headers) + " |"
    data_rows  = [
        "| " + " | ".join(escape_cell(c) for c in row) + " |"
        for row in rows
    ]
    return "\n".join([header_row, separator] + data_rows)


def heading(text: str, level: int = 1) -> str:
    """Return a Markdown heading string.

    Args:
        text: Heading text.
        level: Heading level 1-6.

    Returns:
        Markdown heading, e.g. ``## Title``.
    """
    level = max(1, min(6, level))
    return "#" * level + " " + text.strip()


def fenced_code(code: str, language: str = "") -> str:
    """Wrap *code* in a fenced code block.

    Args:
        code: Source code or text.
        language: Optional language hint (e.g. ``python``).

    Returns:
        Fenced code block string.
    """
    return f"```{language}\n{code}\n```"


def clean_text(text: str) -> str:
    """Remove excessive whitespace from extracted text.

    Args:
        text: Raw text from OCR or document parser.

    Returns:
        Cleaned string with normalised whitespace.
    """
    # Replace runs of whitespace (not newlines) with single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
