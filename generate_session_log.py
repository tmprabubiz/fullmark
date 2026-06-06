"""
generate_session_log.py
------------------------
Reads the Copilot Chat JSONL transcript for this FullMark session,
strips it to plain conversation text, sends it to DeepSeek (via the
OpenAI-compatible API), and writes a numbered iteration journal to:

    For-You_TMP_001.md
    For-You_TMP_002.md   (if the session was too long for one file)
    ...

The files document every decision, error, fix, and learning from
the session — a personal project journal / "what we built and why".

Usage:
    python generate_session_log.py
    python generate_session_log.py --transcript <path>
    python generate_session_log.py --output-dir <dir>

Requires in .env:
    OPENAI_API_KEY=<your DeepSeek key>
    OPENAI_BASE_URL=https://api.deepseek.com/v1

Optional .env overrides:
    SESSION_LOG_MODEL=deepseek-chat      (default)
    SESSION_LOG_CHUNK_CHARS=60000        (chars of transcript per LLM call)
    SESSION_LOG_OUTPUT_DIR=.             (where to write files; default: project root)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("session_log")

# ── Default transcript path (this session) ────────────────────────────────────
_DEFAULT_TRANSCRIPT = (
    r"c:\Users\TMPHOUSE\AppData\Roaming\Code\User\workspaceStorage"
    r"\7e240b551b6cc2385e107cbbf8fcdd1e\GitHub.copilot-chat\transcripts"
    r"\ceed090a-ccaf-4554-948e-eb0ac42acfdf.jsonl"
)

# ── Config from .env ──────────────────────────────────────────────────────────
_MODEL        = os.getenv("SESSION_LOG_MODEL") or os.getenv("DEEPSEEK_MODEL", "gpt-4o")
_CHUNK_CHARS  = int(os.getenv("SESSION_LOG_CHUNK_CHARS", "60000"))
_OUTPUT_DIR   = Path(os.getenv("SESSION_LOG_OUTPUT_DIR", "."))
_MAX_SEG_CHARS = 110_000   # max chars per output .md file before splitting

# ── System prompt sent to DeepSeek ───────────────────────────────────────────
_SYSTEM_PROMPT = """You are documenting a real software development session for the project owner TMP.

Your job: read the conversation excerpt below and write a **detailed, numbered iteration journal** that weaves TMP's own words into the narrative.

Rules:
- Number every distinct action, decision, error, fix, or learning as a separate item.
- Be specific — include file names, function names, exact error messages, and commands used.
- For each item note: what was attempted, what happened (success / failure / warning), and what was learned or fixed.
- Group items under clear H2 headings by theme (e.g. ## Feature Work, ## Bugs & Fixes, ## Design Decisions, ## Lessons Learned, ## User Direction).
- **Every time TMP gave a significant instruction, request, or decision**, quote it verbatim in a `> TMP:` blockquote immediately before or within the numbered item it triggered. Example:
  > TMP: "Yes"
  **7.** Confirmed the SVG image-type fix — agent applied content-type detection in `_collect_images()`.
- At the end, add a dedicated ## User Inputs section that lists every user message in order, numbered, verbatim, with the date/time if visible in the transcript.
- Write in plain English. No filler. No praise. Just facts.
- The audience is TMP reading this in 6 months to recall exactly what was built and why, including every direction they gave.
- If this is a continuation chunk (PART N of M), start numbering from where the previous part left off.
- End with a short ## Summary paragraph for this chunk only.
"""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Parse the JSONL transcript → plain text conversation
# ─────────────────────────────────────────────────────────────────────────────

def _extract_conversation(transcript_path: Path) -> list[dict]:
    """
    Parse the JSONL transcript and return a list of
    {"role": "user"|"assistant", "text": str} dicts.

    Skips tool calls, tool results, turn markers, and session metadata.
    Captures:
      - user.message  → role=user, data.content
      - assistant.message with content → role=assistant, data.content
      - assistant reasoning text when present
    """
    turns: list[dict] = []
    current_assistant_parts: list[str] = []

    with transcript_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type", "")
            data = obj.get("data", {})

            if msg_type == "user.message":
                # Flush any buffered assistant parts first
                if current_assistant_parts:
                    turns.append({
                        "role": "assistant",
                        "text": "\n".join(current_assistant_parts).strip(),
                    })
                    current_assistant_parts = []
                content = data.get("content", "").strip()
                if content:
                    turns.append({"role": "user", "text": content})

            elif msg_type == "assistant.message":
                reasoning = data.get("reasoningText", "").strip()
                content   = data.get("content", "").strip()
                # Collect non-empty text parts (skip pure tool-call messages)
                part = ""
                if reasoning:
                    part += f"[thinking] {reasoning}\n"
                if content:
                    part += content
                if part.strip():
                    current_assistant_parts.append(part.strip())

    # Flush remaining assistant buffer
    if current_assistant_parts:
        turns.append({
            "role": "assistant",
            "text": "\n".join(current_assistant_parts).strip(),
        })

    return turns


def _turns_to_text(turns: list[dict]) -> str:
    """Format the turn list as a readable plain-text transcript."""
    lines = []
    for t in turns:
        prefix = "USER:" if t["role"] == "user" else "ASSISTANT:"
        lines.append(f"{prefix}\n{t['text']}\n")
    return "\n---\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Chunk the plain text for the LLM
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_chars: int) -> list[str]:
    """Split *text* into chunks of at most *chunk_chars* at turn boundaries."""
    # Split at turn boundaries (the --- separator)
    segments = text.split("\n---\n")
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for seg in segments:
        seg_len = len(seg) + 5  # account for separator
        if current_parts and current_len + seg_len > chunk_chars:
            chunks.append("\n---\n".join(current_parts))
            current_parts = [seg]
            current_len = seg_len
        else:
            current_parts.append(seg)
            current_len += seg_len

    if current_parts:
        chunks.append("\n---\n".join(current_parts))

    return chunks or [text]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Call DeepSeek
# ─────────────────────────────────────────────────────────────────────────────

def _call_deepseek(chunk_text: str, part_n: int, total_parts: int) -> str:
    """Send one transcript chunk to DeepSeek and return the Markdown response."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        raise SystemExit("openai package not installed — run: pip install openai")

    api_key  = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY not set in .env — add your DeepSeek key:\n"
            "  OPENAI_API_KEY=sk-...\n"
            "  OPENAI_BASE_URL=https://api.deepseek.com/v1"
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = (
        f"This is PART {part_n} of {total_parts} of the session transcript.\n\n"
        f"--- TRANSCRIPT START ---\n{chunk_text}\n--- TRANSCRIPT END ---\n\n"
        "Write the numbered iteration journal for this part now."
    )

    logger.info("Calling %s — part %d/%d (%d chars)…", _MODEL, part_n, total_parts, len(chunk_text))

    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=8000,
    )
    result = resp.choices[0].message.content or ""
    logger.info(
        "Part %d/%d done — %d input tokens, %d output tokens",
        part_n, total_parts,
        resp.usage.prompt_tokens,
        resp.usage.completion_tokens,
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Write output files
# ─────────────────────────────────────────────────────────────────────────────

def _write_files(sections: list[str], output_dir: Path, max_seg_chars: int) -> list[Path]:
    """
    Combine LLM sections into output files, splitting if a single file
    would exceed *max_seg_chars*.  Files are named For-You_TMP_001.md, etc.
    """
    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build full content
    header = (
        "---\n"
        "title: FullMark — Session Iteration Journal\n"
        f"generated: {now_str}\n"
        "project: FullMark (tmprabubiz/fullmark)\n"
        "author: TMP\n"
        "---\n\n"
        "# FullMark — Session Iteration Journal\n\n"
        "> Every decision, error, fix, and learning from the build session.\n"
        "> Generated from the Copilot Chat transcript by DeepSeek.\n\n"
    )

    full_content = header + "\n\n---\n\n".join(sections)

    # Split into file-sized chunks at H2 boundaries if needed
    if len(full_content) <= max_seg_chars:
        file_chunks = [full_content]
    else:
        # Split at H2 heading boundaries
        import re
        parts = re.split(r'(?=\n## )', full_content)
        file_chunks = []
        current = ""
        for part in parts:
            if len(current) + len(part) > max_seg_chars and current:
                file_chunks.append(current)
                current = part
            else:
                current += part
        if current:
            file_chunks.append(current)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for i, chunk in enumerate(file_chunks, start=1):
        path = output_dir / f"For-You_TMP_{i:03d}.md"
        # Add segment note if multi-file
        if len(file_chunks) > 1:
            segment_note = f"\n\n> *File {i} of {len(file_chunks)}*\n\n"
            chunk = segment_note + chunk if i > 1 else chunk + segment_note
        path.write_text(chunk, encoding="utf-8")
        kb = len(chunk.encode()) / 1024
        logger.info("Wrote %s (%.1f KB)", path, kb)
        written.append(path)

    return written


# ─────────────────────────────────────────────────────────────────────────────
# 5. Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a numbered iteration journal from a Copilot Chat transcript."
    )
    parser.add_argument(
        "--transcript",
        default=_DEFAULT_TRANSCRIPT,
        help="Path to the .jsonl transcript file (default: this session's file)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_OUTPUT_DIR),
        help="Directory to write For-You_TMP_NNN.md files (default: project root)",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=_CHUNK_CHARS,
        help=f"Max chars of transcript per LLM call (default: {_CHUNK_CHARS})",
    )
    args = parser.parse_args()

    transcript_path = Path(args.transcript)
    output_dir      = Path(args.output_dir)

    if not transcript_path.exists():
        raise SystemExit(f"Transcript not found: {transcript_path}\n"
                         "Pass --transcript <path> to override.")

    # Step 1: parse transcript
    logger.info("Parsing transcript: %s", transcript_path)
    turns = _extract_conversation(transcript_path)
    logger.info("Extracted %d turns (user + assistant)", len(turns))

    if not turns:
        raise SystemExit("No conversation turns found in transcript — check the file path.")

    # Step 2: convert to text and chunk
    full_text = _turns_to_text(turns)
    logger.info("Total conversation text: %d chars", len(full_text))
    chunks = _chunk_text(full_text, args.chunk_chars)
    logger.info("Split into %d chunk(s) for LLM processing", len(chunks))

    # Step 3: send each chunk to DeepSeek
    sections: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        result = _call_deepseek(chunk, i, len(chunks))
        sections.append(result)

    # Step 4: write output files
    written = _write_files(sections, output_dir, _MAX_SEG_CHARS)

    print(f"\nDone — {len(written)} file(s) written:")
    for p in written:
        print(f"  {p}")


if __name__ == "__main__":
    main()
