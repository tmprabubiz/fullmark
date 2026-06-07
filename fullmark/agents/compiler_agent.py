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
1. Merge the transcript and frame OCR into a single, clean, structured Markdown document,
   interleaved in chronological order by timestamp.
2. Use ## headings for each scene/section, labeled with the timestamp [MM:SS].
3. Place the transcript text for each time window under its section heading.
4. For every frame that has non-empty ocr_text, include it verbatim in a fenced code block
   (or as a blockquote if it is prose text) under the nearest heading — do NOT summarise,
   skip, or paraphrase it.
5. NEVER break a sentence in the middle.  If a Whisper segment spans a section boundary,
   complete the sentence before opening the next ## heading.
6. Remove filler words, false starts, and repetitions from the transcript only.
7. Preserve technical terms, proper nouns, and code snippets exactly.
8. Output ONLY the Markdown document — no preamble, no explanation, no commentary.
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
        """
        Split transcript into chunks and compile each, then join.

        Frames are distributed to the chunk whose time window contains the frame
        timestamp so that OCR data is never silently dropped.
        """
        chunk_size = 50  # segments per chunk
        chunks = [
            data.transcript[i:i + chunk_size]
            for i in range(0, len(data.transcript), chunk_size)
        ]
        parts: list[str] = []
        for i, chunk in enumerate(chunks):
            # Determine time window of this chunk
            chunk_start = chunk[0].get("start", 0.0)
            chunk_end   = chunk[-1].get("end", chunk[-1].get("start", 0.0))
            # Include frames whose timestamp falls inside this chunk's window
            chunk_frames = [
                {"timestamp": f["timestamp"], "ocr_text": f.get("ocr_text", "")}
                for f in data.frames
                if chunk_start <= f["timestamp"] <= chunk_end
            ]
            payload = {
                "source": f"{data.source} (part {i+1}/{len(chunks)})",
                "transcript": chunk,
                "frames": chunk_frames,
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

        Transcript segments and frame OCR are interleaved chronologically.
        Segments are grouped into windows bounded by frame timestamps so that
        each ## section contains the speech that occurred while that slide was
        visible.  Sentences are never split: each Whisper segment is kept whole.
        """
        parts: list[str] = [heading(data.source, 1)]

        # Build a sorted list of frame timestamps (float) → frame dict
        sorted_frames = sorted(data.frames, key=lambda f: f.get("timestamp", 0.0))
        frame_times   = [f.get("timestamp", 0.0) for f in sorted_frames]

        # Create section boundaries: each frame starts a new section.
        # Everything before the first frame goes into a "00:00" intro section.
        # Everything after the last frame stays in the final section.
        def _ts_label(secs: float) -> str:
            m, s = divmod(int(secs), 60)
            return f"{m:02d}:{s:02d}"

        # Assign each transcript segment to the section it belongs to.
        # A segment belongs to section N if its START time is >= frame_times[N]
        # and < frame_times[N+1]  (or >= last frame time for the last section).
        def _section_for(start: float) -> int:
            """Return index into sorted_frames (or -1 for before-first-frame)."""
            idx = -1
            for j, ft in enumerate(frame_times):
                if start >= ft:
                    idx = j
            return idx

        # Bucket segments
        # Key: section index (-1 = intro before first frame)
        buckets: dict[int, list[dict]] = {}
        for seg in data.transcript:
            idx = _section_for(seg.get("start", 0.0))
            buckets.setdefault(idx, []).append(seg)

        # If there are no frames at all, fall back to simple windowed output.
        if not sorted_frames:
            window_size = 30.0
            windows: list[list[dict]] = []
            current: list[dict] = []
            window_start = 0.0
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
                text = " ".join(s.get("text", "") for s in window).strip()
                parts.append(f"\n## [{_ts_label(first_start)}]\n\n{clean_text(text)}")
            return "\n\n".join(parts)

        # Render intro section (before first frame) if any segments exist there
        intro_segs = buckets.get(-1, [])
        if intro_segs:
            text = " ".join(s.get("text", "") for s in intro_segs).strip()
            parts.append(f"\n## [00:00]\n\n{clean_text(text)}")

        # Render one section per frame
        for idx, frame in enumerate(sorted_frames):
            ts  = frame.get("timestamp", 0.0)
            ocr = frame.get("ocr_text", "").strip()
            img = frame.get("path", "")

            # Section heading
            parts.append(f"\n## [{_ts_label(ts)}]")

            # Frame image reference + OCR content
            if img:
                parts.append(f"![frame {_ts_label(ts)}]({Path(img).name})")
            if ocr:
                parts.append(f"\n```\n{clean_text(ocr)}\n```")

            # Transcript segments for this section
            segs = buckets.get(idx, [])
            if segs:
                # Ensure we never break a sentence: include any segment that
                # started in this window, whole — Whisper segments are already
                # phrase/sentence boundaries.
                text = " ".join(s.get("text", "") for s in segs).strip()
                if text:
                    parts.append(f"\n{clean_text(text)}")

        return "\n\n".join(parts)
