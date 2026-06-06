"""
fullmark/utils/metadata_logger.py
----------------------------------
Conversion metadata logger.

Records every converted source into:
  <OUTPUT_DIR>/conversion_log.json  — machine-readable, append-across-runs
  <OUTPUT_DIR>/conversion_log.md   — human-readable Markdown summary

Why this matters
----------------
- Deduplication: ``already_converted()`` checks the hash of a source file/URL
  so re-running FullMark on the same content skips work already done.
- Auditability: every conversion records char count, token estimate, agent
  used, and output file paths.
- Ecosystem memory: for cohesive document sets (e.g. a SharePoint export),
  the log tracks which files came from the same source and when they were last
  converted, preventing unnecessary rework.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4  # rough estimate — GPT-4 ~3.5 chars/token, Llama ~4


class MetadataLogger:
    """
    Records and persists conversion metadata for an Orchestrator run.

    One instance is shared for an entire run. Call ``record()`` after each
    successful conversion and ``write_summary()`` at the end of the session.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.log_path = output_dir / "conversion_log.json"
        self._entries: list[dict] = self._load_existing()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def record(
        self,
        source: str,
        agent: str,
        output_files: list[Path],
        markdown: str,
        extra_meta: dict | None = None,
    ) -> dict:
        """
        Record a completed conversion.

        Args:
            source: Original file path or URL.
            agent: Name of the agent that produced the output.
            output_files: Written output paths (may be multiple if segmented).
            markdown: Full Markdown string (used to compute char/token counts).
            extra_meta: Optional additional key-value metadata to store.

        Returns:
            The recorded metadata dict.
        """
        char_count = len(markdown)
        token_estimate = char_count // _CHARS_PER_TOKEN
        content_hash = self._compute_hash(source)

        entry: dict = {
            "source": source,
            "agent": agent,
            "converted": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "output_files": [str(p) for p in output_files],
            "segments": len(output_files),
            "char_count": char_count,
            "token_estimate": token_estimate,
            "content_hash": content_hash,
        }
        if extra_meta:
            entry["meta"] = extra_meta

        self._entries.append(entry)
        self._flush_json()
        logger.debug(
            "Logged: %s → %s (%d chars, ~%d tokens)",
            source, agent, char_count, token_estimate,
        )
        return entry

    def already_converted(self, source: str) -> Optional[dict]:
        """
        Return the most recent log entry for *source* if it has been converted
        in a previous run, or ``None`` if not found.

        Uses content hash — so the same file with different names is detected.

        Args:
            source: Source path or URL to look up.

        Returns:
            Most recent log entry dict, or ``None``.
        """
        content_hash = self._compute_hash(source)
        matches = [e for e in self._entries if e.get("content_hash") == content_hash]
        return matches[-1] if matches else None

    def write_summary(self) -> Path:
        """
        Write a human-readable Markdown summary of all conversions.

        Returns:
            Path to the written ``conversion_log.md`` file.
        """
        summary_path = self.output_dir / "conversion_log.md"
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        total_chars = sum(e.get("char_count", 0) for e in self._entries)
        total_tokens = sum(e.get("token_estimate", 0) for e in self._entries)

        lines = [
            "---",
            "title: FullMark Conversion Log",
            f"generated: {now}",
            f"total_conversions: {len(self._entries)}",
            "---",
            "",
            "# FullMark Conversion Log",
            "",
            f"**Total conversions:** {len(self._entries)}  ",
            f"**Total characters:** {total_chars:,}  ",
            f"**Estimated tokens:** ~{total_tokens:,}",
            "",
            "| # | Source | Agent | Segs | Chars | ~Tokens | Date |",
            "|---|--------|-------|------|-------|---------|------|",
        ]

        for i, e in enumerate(self._entries, 1):
            src = str(e.get("source", ""))
            # Truncate long sources for readability
            src_display = (src[:55] + "…") if len(src) > 55 else src
            agent = e.get("agent", "")
            segs = e.get("segments", 1)
            chars = f"{e.get('char_count', 0):,}"
            tokens = f"~{e.get('token_estimate', 0):,}"
            ts = e.get("converted", "")[:10]
            lines.append(f"| {i} | `{src_display}` | {agent} | {segs} | {chars} | {tokens} | {ts} |")

        lines.extend([
            "",
            "## Output Files",
            "",
        ])
        for e in self._entries:
            for f_str in e.get("output_files", []):
                f_path = Path(f_str)
                seg_count = e.get("segments", 1)
                segs_note = f" *(segment {seg_count} of {seg_count})*" if seg_count > 1 else ""
                lines.append(f"- [{f_path.name}]({f_path.name}){segs_note}")

        if self._entries:
            lines.extend([
                "",
                "## Metadata Details",
                "",
                "```json",
                json.dumps(
                    [
                        {k: v for k, v in e.items() if k != "meta"}
                        for e in self._entries[-10:]  # last 10 for brevity
                    ],
                    indent=2,
                    ensure_ascii=False,
                ),
                "```",
            ])

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Wrote conversion summary → %s (%d entries)", summary_path, len(self._entries))
        return summary_path

    # ──────────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────────

    def _load_existing(self) -> list[dict]:
        """Load existing JSON log to support append-across-runs."""
        if self.log_path.exists():
            try:
                with self.log_path.open(encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    logger.debug("Loaded %d existing log entries from %s", len(data), self.log_path)
                    return data
            except Exception as exc:
                logger.debug("Could not load existing conversion log: %s", exc)
        return []

    def _flush_json(self) -> None:
        """Write the in-memory entries to the JSON log file."""
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text(
                json.dumps(self._entries, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Could not write conversion log: %s", exc)

    @staticmethod
    def _compute_hash(source: str) -> str:
        """
        Compute a stable 16-char hex identifier for *source*.

        For existing files: SHA256 of the first 512 KB of file contents.
        For URLs or missing paths: SHA256 of the source string itself.
        """
        path = Path(source)
        if not source.startswith(("http://", "https://")) and path.exists() and path.is_file():
            try:
                data = path.read_bytes()[:524288]  # first 512 KB
                return hashlib.sha256(data).hexdigest()[:16]
            except Exception:
                pass
        return hashlib.sha256(source.encode()).hexdigest()[:16]
