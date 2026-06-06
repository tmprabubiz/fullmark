"""
fullmark/agents/code_agent.py
------------------------------
Converts source-code and configuration files to fenced Markdown code blocks.

Handles any file extension listed in ``fullmark.utils.file_utils.CODE_EXTENSIONS``.
Also serves as the fallback for plain-text files the DocumentAgent doesn't cover.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fullmark import AgentError
from fullmark.utils.file_utils import LANG_MAP
from fullmark.utils.markdown_utils import front_matter

logger = logging.getLogger(__name__)

_AGENT_NAME = "CodeAgent"

# Files larger than this (bytes) are summarised rather than embedded in full
_MAX_EMBED_BYTES: int = 500_000  # 500 KB

# Encodings to try when reading a file
_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")


class CodeAgent:
    """
    Convert source-code and config files to Markdown with syntax highlighting.

    Each file becomes a fenced code block tagged with its language.
    """

    def convert(self, source: str | Path) -> str:
        """
        Convert a single code/config file to a Markdown string.

        Args:
            source: Path to the file.

        Returns:
            Markdown string with YAML front matter and fenced code block.

        Raises:
            AgentError: If the file cannot be read.
        """
        path = Path(source)
        if not path.exists():
            raise AgentError(f"File not found: {path}")

        size = path.stat().st_size
        ext = path.suffix.lower()
        lang = LANG_MAP.get(ext, "")

        # Handle special no-extension files (Dockerfile, Makefile, .gitignore)
        if not ext:
            name_lower = path.name.lower()
            lang = _NO_EXT_LANG.get(name_lower, "")

        if size == 0:
            body = f"## {path.name}\n\n*Empty file.*"
        elif size > _MAX_EMBED_BYTES:
            kb = size / 1024
            body = (
                f"## {path.name}\n\n"
                f"*File too large to embed ({kb:.0f} KB). "
                f"Only the first 200 lines are shown.*\n\n"
            )
            body += self._read_lines(path, max_lines=200, lang=lang)
        else:
            content = self._read_text(path)
            body = f"## {path.name}\n\n" + _fenced(content, lang)

        fm = front_matter(path.name, _AGENT_NAME)
        return f"{fm}\n\n{body}"

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _read_text(self, path: Path) -> str:
        """Try multiple encodings; return text or a placeholder on failure."""
        for enc in _ENCODINGS:
            try:
                return path.read_text(encoding=enc)
            except (UnicodeDecodeError, ValueError):
                continue
        # Binary file — not really a code file
        raise AgentError(f"Cannot decode {path.name} as text (may be binary)")

    def _read_lines(self, path: Path, max_lines: int, lang: str) -> str:
        """Read the first *max_lines* lines and return as a fenced block."""
        lines: list[str] = []
        for enc in _ENCODINGS:
            try:
                with path.open(encoding=enc, errors="replace") as f:
                    for _ in range(max_lines):
                        line = f.readline()
                        if not line:
                            break
                        lines.append(line)
                break
            except Exception:
                continue
        return _fenced("".join(lines), lang)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fenced(content: str, lang: str = "") -> str:
    """Wrap *content* in a triple-backtick fenced code block."""
    # Escape any triple backtick sequences inside the content
    content = content.replace("```", "` ` `")
    return f"```{lang}\n{content}\n```"


# Language tags for files with no extension
_NO_EXT_LANG: dict[str, str] = {
    "dockerfile":   "dockerfile",
    "makefile":     "makefile",
    "gemfile":      "ruby",
    "rakefile":     "ruby",
    "vagrantfile":  "ruby",
    "jenkinsfile":  "groovy",
    "procfile":     "yaml",
    ".gitignore":   "gitignore",
    ".gitattributes": "ini",
    ".editorconfig": "ini",
}
