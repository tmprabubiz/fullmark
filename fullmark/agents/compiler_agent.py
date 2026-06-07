"""
fullmark/agents/compiler_agent.py
----------------------------------
Merges Whisper transcript + frame OCR data into structured Markdown.

Uses the model_client fallback chain (Gemini → OpenAI-compatible → Ollama → mechanical).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from fullmark.utils.markdown_utils import clean_text, heading

logger = logging.getLogger(__name__)

_AGENT_NAME = "CompilerAgent"
_MAX_PROMPT_CHARS = 24_000  # ~6k tokens — safe for most free models

_SYSTEM_PROMPT = """\
You are a technical transcription formatter.
You will receive a JSON object with:
  - "source": original filename
  - "transcript": list of {start, end, text} segments from Whisper
  - "frames": list of {timestamp, ocr_text} from video frame OCR

Your task:
1. Merge the transcript and frame OCR into a single, clean, structured Markdown document.
2. Use ## headings for each scene/section, labeled with the timestamp [MM:SS].
3. Place the transcript text for each time window under its section.
4. For every frame that has non-empty ocr_text, you MUST include it verbatim in a
   fenced code block (or as a blockquote if it is prose text) under the nearest
   heading — do NOT summarise, skip, or paraphrase it.
5. Remove filler words, false starts, and repetitions from the transcript only.
6. Preserve technical terms, proper nouns, and code snippets exactly.
7. Output ONLY the Markdown document — no preamble or explanation.
"""


@dataclass
class CompilerInput:
    source: str
    transcript: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)


class CompilerAgent:
    """
    Merge transcript + frame OCR data into structured Markdown using an LLM.

    Falls back to mechanical formatting if no LLM is available.
    """

    def compile(self, data: CompilerInput) -> str:
        """
        Compile *data* into a Markdown string.

        Args:
            data: CompilerInput with transcript segments and frame data.

        Returns:
            Structured Markdown string.
        """
        if not data.transcript and not data.frames:
            return f"*No content extracted from {data.source}*"

        # Try LLM compilation
        llm_result = self._llm_compile(data)
        if llm_result:
            return llm_result

        # Mechanical fallback
        logger.warning("No LLM available — using mechanical formatting for %s", data.source)
        return self._mechanical_compile(data)

    # ──────────────────────────────────────────────────────────────────────────
    # LLM path
    # ──────────────────────────────────────────────────────────────────────────

    def _llm_compile(self, data: CompilerInput) -> str | None:
        from fullmark.utils.model_client import ModelClient
        client = ModelClient()

        payload = {
            "source": data.source,
            "transcript": data.transcript,
            "frames": [
                {"timestamp": f["timestamp"], "ocr_text": f.get("ocr_text", "")}
                for f in data.frames
            ],
        }
        prompt_json = json.dumps(payload, ensure_ascii=False)

        # Chunk if too large
        if len(prompt_json) > _MAX_PROMPT_CHARS:
            return self._llm_compile_chunked(data, client)

        return client.complete(prompt_json, system=_SYSTEM_PROMPT)

    def _llm_compile_chunked(self, data: CompilerInput, client) -> str | None:
        """Split transcript into chunks and compile each, then join."""
        chunk_size = 50  # segments per chunk
        chunks = [
            data.transcript[i:i + chunk_size]
            for i in range(0, len(data.transcript), chunk_size)
        ]
        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            payload = {
                "source": f"{data.source} (part {i+1}/{len(chunks)})",
                "transcript": chunk,
                "frames": [],
            }
            result = client.complete(json.dumps(payload), system=_SYSTEM_PROMPT)
            if result:
                parts.append(result)
        return "\n\n".join(parts) if parts else None

    # ──────────────────────────────────────────────────────────────────────────
    # Mechanical fallback
    # ──────────────────────────────────────────────────────────────────────────

    def _mechanical_compile(self, data: CompilerInput) -> str:
        """
        Format transcript and frames into Markdown without LLM.
        Groups transcript segments into ~30-second scenes.
        """
        parts: list[str] = [heading(data.source, 1)]

        if data.transcript:
            parts.append(heading("Transcript", 2))
            # Group into 30-second windows
            windows: list[list[dict]] = []
            current: list[dict] = []
            window_start = 0.0
            window_size  = 30.0

            for seg in data.transcript:
                start = seg.get("start", 0.0)
                if start - window_start >= window_size and current:
                    windows.append(current)
                    current = []
                    window_start = start
                current.append(seg)
            if current:
                windows.append(current)

            for window in windows:
                first_start = window[0].get("start", 0.0)
                mins = int(first_start) // 60
                secs = int(first_start) % 60
                text = " ".join(s.get("text", "") for s in window).strip()
                parts.append(f"\n### [{mins:02d}:{secs:02d}]\n\n{clean_text(text)}")

        if data.frames:
            parts.append(heading("Frame OCR", 2))
            for frame in data.frames:
                ts  = frame.get("timestamp", 0.0)
                ocr = frame.get("ocr_text", "").strip()
                img = frame.get("path", "")
                mins = int(ts) // 60
                secs = int(ts) % 60
                parts.append(f"\n#### Frame [{mins:02d}:{secs:02d}]")
                if img:
                    parts.append(f"![frame {mins:02d}:{secs:02d}]({Path(img).name})")
                if ocr:
                    parts.append(f"\n```\n{clean_text(ocr)}\n```")
                else:
                    parts.append("*(no OCR text detected in this frame)*")

        return "\n\n".join(parts)
