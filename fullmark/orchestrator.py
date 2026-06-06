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
from fullmark.utils.file_utils import detect_agent, unpack_zip, safe_output_path, is_url_list_file
from fullmark.utils.metadata_logger import MetadataLogger

load_dotenv()
logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Route any input source to the correct FullMark agent and write output.

    Attributes:
        output_dir: Directory where converted ``.md`` files are written.
    """

    _MAX_FILE_CHARS: int = 120_000

    def __init__(self, output_dir: str | Path | None = None) -> None:
        default = os.getenv("OUTPUT_DIR", "./output")
        self.output_dir = Path(output_dir or default)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Always ensure input/ folder exists alongside output/
        Path("input").mkdir(exist_ok=True)
        self._meta_log = MetadataLogger(self.output_dir)

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
            if self._should_skip(source_str):
                return results
            md = self._run_agent("web", source_str)
            if md:
                results.append((source_str, md))
                self._write(source_str, md, "web")
            self._meta_log.write_summary()
            return results

        path = Path(source_str)

        # Directory — walk and route each file
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    result = self._convert_file(child)
                    if result:
                        results.append(result)
            self._meta_log.write_summary()
            return results

        # Single file
        result = self._convert_file(path)
        if result:
            results.append(result)
        self._meta_log.write_summary()
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
        if self._should_skip(str(path)):
            return None

        # Check for URL-list files before normal agent routing
        if is_url_list_file(path):
            logger.info("routing %s → UrlListAgent (URL-list file)", path.name)
            try:
                md = self._run_agent("url_list", path)
            except Exception as exc:
                logger.error("UrlListAgent failed on %s: %s", path, exc)
                return None
            if md:
                self._write(str(path), md, "url_list")
                return (str(path), md)
            return None

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
            self._write(str(path), md, agent_name)
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
            self._write(str(zip_path), combined, "archive")
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
        if agent_name == "url_list":
            from fullmark.agents.web_agent import UrlListAgent
            return UrlListAgent().convert(source)
        return None

    def _write(self, source: str, markdown: str, agent_name: str = "unknown") -> list[Path]:
        """
        Write *markdown* to output file(s).

        If ``len(markdown) <= _MAX_FILE_CHARS``, writes a single ``.md`` file.
        Otherwise splits at paragraph boundaries and writes
        ``stem_001.md``, ``stem_002.md`` etc.

        Returns:
            List of Paths written.
        """
        base_path = safe_output_path(source, self.output_dir)
        stem = base_path.stem
        chunks = self._split_markdown(markdown)

        if len(chunks) == 1:
            base_path.write_text(chunks[0], encoding="utf-8")
            kb = len(chunks[0].encode()) / 1024
            logger.info("wrote %s (%.1f KB)", base_path, kb)
            written = [base_path]
        else:
            written = []
            for i, chunk in enumerate(chunks, start=1):
                seg_path = self.output_dir / f"{stem}_{i:03d}.md"
                seg_path.write_text(chunk, encoding="utf-8")
                kb = len(chunk.encode()) / 1024
                logger.info("wrote %s (%.1f KB)", seg_path, kb)
                written.append(seg_path)

        self._meta_log.record(
            source=source,
            agent=agent_name,
            output_files=[str(p) for p in written],
            markdown=markdown,
        )
        return written

    @staticmethod
    def _split_markdown(text: str, max_chars: int = _MAX_FILE_CHARS) -> list[str]:
        """
        Split *text* into chunks of at most *max_chars*, breaking at paragraph
        boundaries (double newlines) where possible.

        Args:
            text: Full Markdown text.
            max_chars: Maximum character count per chunk.

        Returns:
            List of text chunks.
        """
        if len(text) <= max_chars:
            return [text]

        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para) + 2  # account for the \n\n we'll rejoin with
            if current and current_len + para_len > max_chars:
                chunks.append("\n\n".join(current))
                current = [para]
                current_len = para_len
            else:
                current.append(para)
                current_len += para_len

        if current:
            chunks.append("\n\n".join(current))

        return chunks or [text]

    def _should_skip(self, source: str) -> bool:
        """Return True if SKIP_EXISTING is set and *source* is already logged."""
        if os.getenv("SKIP_EXISTING", "").lower() in ("1", "true", "yes"):
            if self._meta_log.already_converted(source):
                logger.info("Skipping already-converted source: %s", source)
                return True
        return False

    def convert_input_folder(self) -> list[tuple[str, str]]:
        """
        Scan the ``input/`` folder in the current directory and convert all files.

        Returns:
            List of (source_path, markdown) tuples.
        """
        input_dir = Path("input")
        if not input_dir.exists() or not input_dir.is_dir():
            logger.warning("input/ folder not found")
            return []

        files = sorted(f for f in input_dir.rglob("*") if f.is_file())
        if not files:
            logger.info("input/ folder is empty — nothing to convert")
            return []

        results: list[tuple[str, str]] = []
        for f in files:
            result = self._convert_file(f)
            if result:
                results.append(result)

        self._meta_log.write_summary()
        return results
