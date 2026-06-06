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
        source_id = "fm-" + content_hash

        entry: dict = {
            "source": source,
            "source_id": source_id,
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
        in a previous run **and all its output files still exist** on disk.

        If the output files have been deleted the entry is ignored — FullMark
        will reconvert without the user needing to use ``--force``.

        Args:
            source: Source path or URL to look up.

        Returns:
            Most recent log entry dict, or ``None``.
        """
        content_hash = self._compute_hash(source)
        matches = [e for e in self._entries if e.get("content_hash") == content_hash
                   or e.get("source_id") == "fm-" + content_hash]
        if not matches:
            return None
        entry = matches[-1]
        # Verify at least one output file still exists; if all are gone, treat
        # as unconverted so the user doesn't need --force after deleting output.
        output_files = entry.get("output_files", [])
        if output_files and not any(Path(p).exists() for p in output_files):
            logger.debug(
                "Log entry for %s found but output files are missing — will reconvert", source
            )
            return None
        return entry

    def write_skip_notice(self, source: str, entry: dict) -> None:
        """
        Append a human-readable skip notice to ``conversion_skipped.log``.

        Called by the orchestrator whenever a source is skipped because a
        previous conversion is still on disk.  The notice tells the user:
        - what was skipped
        - when it was previously converted
        - where the existing output files are
        - how to force a re-conversion

        Args:
            source: The source that was skipped.
            entry:  The matching log entry returned by ``already_converted()``.
        """
        skip_log = self.output_dir / "conversion_skipped.log"
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        converted_at = entry.get("converted", "unknown")[:19].replace("T", " ") + " UTC"
        source_id = entry.get("source_id", entry.get("content_hash", "?"))
        output_files = entry.get("output_files", [])
        files_block = "\n".join(f"    {p}" for p in output_files) or "    (none recorded)"

        lines = [
            f"[{now}] SKIPPED — already converted",
            f"  Source    : {source}",
            f"  ID        : {source_id}",
            f"  Converted : {converted_at}",
            f"  Output    :",
            files_block,
            f"  To reconvert : fullmark_cli.py {source} --force",
            f"  To delete & redo: delete the output file(s) above, then run again",
            "",
        ]
        try:
            skip_log.parent.mkdir(parents=True, exist_ok=True)
            with skip_log.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.debug("Could not write skip log: %s", exc)

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
            "| # | Source | ID | Agent | Segs | Chars | ~Tokens | Date |",
            "|---|--------|-----|-------|------|-------|---------|------|",
        ]

        for i, e in enumerate(self._entries, 1):
            src = str(e.get("source", ""))
            # Truncate long sources for readability
            src_display = (src[:50] + "…") if len(src) > 50 else src
            sid = e.get("source_id", e.get("content_hash", ""))[:10]
            agent = e.get("agent", "")
            segs = e.get("segments", 1)
            chars = f"{e.get('char_count', 0):,}"
            tokens = f"~{e.get('token_estimate', 0):,}"
            ts = e.get("converted", "")[:10]
            lines.append(f"| {i} | `{src_display}` | `{sid}` | {agent} | {segs} | {chars} | {tokens} | {ts} |")

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

        Identity rules by type
        ----------------------
        URL (http/https)
            SHA256 of the *normalised* URL string.
            Normalisation: lowercase scheme + netloc, strip trailing ``/``,
            strip ``.git`` suffix, remove tracking query params
            (``utm_*``, ``fbclid``, ``gclid``, ``ref``, ``source``).

        Local file < 10 MB
            SHA256 of the full file bytes — detects same file under a
            different name; covers PDF, DOCX, XLSX, PPTX, images, etc.

        Local file ≥ 10 MB (video / audio)
            SHA256 of the first 4 MB — strong fingerprint without reading
            the whole file for large media.
        """
        _TRACKING_PARAMS = frozenset({
            "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "fbclid", "gclid", "ref", "source",
        })
        _10MB = 10 * 1024 * 1024
        _4MB  =  4 * 1024 * 1024

        if source.startswith(("http://", "https://")):
            from urllib.parse import urlparse, urlencode, parse_qsl
            p = urlparse(source)
            normalised_path = p.path.rstrip("/").removesuffix(".git")
            filtered_qs = urlencode(
                [(k, v) for k, v in parse_qsl(p.query)
                 if k.lower() not in _TRACKING_PARAMS]
            )
            normalised = p._replace(
                scheme=p.scheme.lower(),
                netloc=p.netloc.lower(),
                path=normalised_path,
                query=filtered_qs,
                fragment="",
            ).geturl()
            return hashlib.sha256(normalised.encode()).hexdigest()[:16]

        path = Path(source)
        if path.exists() and path.is_file():
            try:
                size = path.stat().st_size
                with path.open("rb") as fh:
                    data = fh.read(_4MB if size >= _10MB else size)
                return hashlib.sha256(data).hexdigest()[:16]
            except Exception:
                pass

        return hashlib.sha256(source.encode()).hexdigest()[:16]

    @classmethod
    def compute_source_id(cls, source: str) -> str:
        """Return the canonical ``fm-<hash>`` identifier for *source*."""
        return "fm-" + cls._compute_hash(source)
