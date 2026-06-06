"""
fullmark/orchestrator.py
------------------------
Main orchestrator — detects input type and routes to the correct agent.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from fullmark import AgentError
from fullmark.utils.file_utils import detect_agent, unpack_zip, safe_output_path

load_dotenv()
logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Route any input source to the correct FullMark agent and write output.

    Attributes:
        output_dir: Directory where converted ``.md`` files are written.
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        default = os.getenv("OUTPUT_DIR", "./output")
        self.output_dir = Path(output_dir or default)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def convert(self, source: str | Path) -> list[tuple[str, str]]:
        """
        Convert *source* to Markdown. Handles files, directories, and URLs.

        Args:
            source: File path, directory path, or URL string.

        Returns:
            List of ``(source_path_or_url, markdown_string)`` tuples.
        """
        source_str = str(source)
        results: list[tuple[str, str]] = []

        # URL
        if source_str.startswith(("http://", "https://")):
            md = self._run_agent("web", source_str)
            if md:
                results.append((source_str, md))
                self._write(source_str, md)
            return results

        path = Path(source_str)

        # Directory — walk and route each file
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    result = self._convert_file(child)
                    if result:
                        results.append(result)
            return results

        # Single file
        result = self._convert_file(path)
        if result:
            results.append(result)
        return results

    def convert_file(self, path: Path) -> str:
        """
        Convert a single file and return the Markdown string.

        Args:
            path: Path to the file.

        Returns:
            Markdown string.

        Raises:
            AgentError: If the file cannot be converted.
        """
        result = self._convert_file(path)
        if result is None:
            raise AgentError(f"Cannot convert {path}: unknown file type")
        return result[1]

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_file(self, path: Path) -> tuple[str, str] | None:
        agent_name = detect_agent(path)
        logger.info("routing %s → %sAgent", path.name, agent_name.capitalize())

        if agent_name == "unknown":
            logger.warning("Skipping %s — no agent for this type", path.name)
            return None

        if agent_name == "archive":
            return self._handle_zip(path)

        try:
            md = self._run_agent(agent_name, path)
        except Exception as exc:
            logger.error("Agent %r failed on %s: %s", agent_name, path, exc)
            return None

        if md:
            self._write(str(path), md)
            return (str(path), md)
        return None

    def _handle_zip(self, zip_path: Path) -> tuple[str, str] | None:
        """Unpack ZIP and convert each entry; return combined Markdown."""
        temp_dir: Path | None = None
        try:
            temp_dir, entries = unpack_zip(zip_path)
            parts: list[str] = [f"# Archive: {zip_path.name}\n"]
            for entry in entries:
                agent_name = detect_agent(entry)
                if agent_name in ("unknown", "archive"):
                    logger.warning("Skipping archive entry %s", entry.name)
                    continue
                try:
                    md = self._run_agent(agent_name, entry)
                    if md:
                        parts.append(f"\n---\n\n## {entry.name}\n\n{md}")
                except Exception as exc:
                    logger.error("Failed to convert archive entry %s: %s", entry.name, exc)

            combined = "\n".join(parts)
            self._write(str(zip_path), combined)
            return (str(zip_path), combined)
        finally:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_agent(self, agent_name: str, source: str | Path) -> str | None:
        """Instantiate and run the named agent on *source*."""
        if agent_name == "document":
            from fullmark.agents.document_agent import DocumentAgent
            return DocumentAgent().convert(source)
        if agent_name == "web":
            from fullmark.agents.web_agent import WebAgent
            return WebAgent().convert(source)
        if agent_name == "image":
            from fullmark.agents.image_agent import ImageAgent
            return ImageAgent().convert(source)
        if agent_name == "video":
            from fullmark.agents.video_agent import VideoAgent
            return VideoAgent().convert(source)
        return None

    def _write(self, source: str, markdown: str) -> None:
        """Write *markdown* to the appropriate output file."""
        out_path = safe_output_path(source, self.output_dir)
        out_path.write_text(markdown, encoding="utf-8")
        kb = len(markdown.encode()) / 1024
        logger.info("wrote %s (%.1f KB)", out_path, kb)
