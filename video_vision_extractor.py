#!/usr/bin/env python3
"""
video_vision_extractor.py
─────────────────────────
Standalone tool: extract visual content from a video using OpenAI vision model.

Strategy:
  1. Extract frames at scene-change boundaries (PySceneDetect) +
     fixed-interval fallback every INTERVAL_SECONDS.
  2. Deduplicate via perceptual hashing (imagehash) — skip frames that look
     nearly identical to the previous accepted frame.
  3. Upscale any frame below MIN_WIDTH px using Pillow LANCZOS before sending
     to the vision API (saves tokens AND gets better OCR from the model).
  4. Send each unique frame to GPT-4o-mini vision with a prompt that asks
     to describe data-rich content (code, slides, charts, diagrams, tables).
     Frames that are "just a talking head / blank / no data" are skipped
     via the model's own judgement ("NO_VISUAL_DATA" sentinel).
  5. Write a Markdown file alongside the existing transcript file with the
     suffix _Video.md.

Usage:
    python video_vision_extractor.py "G:/fullmark/input/Claude FULL COURSE 1 HOUR.mp4"

    # Override output location:
    python video_vision_extractor.py <video> --output <path/to/output.md>

    # Tune extraction aggressiveness (lower = more frames):
    python video_vision_extractor.py <video> --hash-threshold 8 --interval 15

Environment variables (loaded from .env in the same directory as this script):
    OPENAI_API_KEY      – required
    OPENAI_BASE_URL     – optional (default: https://api.openai.com/v1)
    OPENAI_VISION_MODEL – optional (default: gpt-4o-mini)
    OUTPUT_DIR          – optional (default: ./output)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

# ─── third-party (imported lazily so missing deps give clear errors) ─────────
# PIL, imagehash, openai  — see _check_deps()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── tunable defaults ─────────────────────────────────────────────────────────
INTERVAL_SECONDS   = 10      # fixed-interval fallback between frames
HASH_THRESHOLD     = 10      # hamming distance above which a frame is "new"
MIN_WIDTH          = 1280    # upscale frames narrower than this
JPEG_QUALITY       = 90      # quality of re-encoded JPEG sent to the API
MAX_TOKENS_REPLY   = 1024    # max tokens in vision model reply
VISION_MODEL       = "gpt-4o-mini"
SCENE_THRESHOLD    = 27.0    # PySceneDetect ContentDetector threshold
API_CALL_DELAY     = 1.5     # seconds between API calls (avoids 429 rate-limit burst)


# ─────────────────────────────────────────────────────────────────────────────
# Dependency check
# ─────────────────────────────────────────────────────────────────────────────

def _check_deps() -> None:
    missing = []
    for pkg in ("PIL", "imagehash", "openai"):
        try:
            __import__(pkg if pkg != "PIL" else "PIL.Image")
        except ImportError:
            missing.append(pkg)
    if missing:
        sys.exit(
            f"[ERROR] Missing Python packages: {', '.join(missing)}\n"
            "Install with:\n"
            "  pip install Pillow imagehash openai\n"
        )
    import shutil
    if not shutil.which("ffmpeg"):
        sys.exit("[ERROR] ffmpeg not found on PATH — install ffmpeg first.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Frame extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def _video_duration(video_path: Path) -> float:
    """Return duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        logger.warning("ffprobe could not determine duration — using fallback")
        return 0.0


def _extract_frame_at(video_path: Path, timestamp: float, out_path: Path) -> bool:
    """Extract a single frame at *timestamp* seconds. Returns True on success."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",        # high quality JPEG
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0


def _scene_change_timestamps(video_path: Path) -> list[float]:
    """Return scene-change timestamps (seconds) using PySceneDetect."""
    try:
        from scenedetect import open_video, SceneManager  # type: ignore
        from scenedetect.detectors import ContentDetector  # type: ignore
    except ImportError:
        logger.info("PySceneDetect not installed — using fixed-interval only")
        return []

    try:
        video = open_video(str(video_path))
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=SCENE_THRESHOLD))
        manager.detect_scenes(video, show_progress=False)
        scenes = manager.get_scene_list()
        timestamps = [s[0].get_seconds() for s in scenes]
        logger.info("PySceneDetect found %d scene changes", len(timestamps))
        return timestamps
    except Exception as exc:
        logger.warning("Scene detection failed: %s", exc)
        return []


def _collect_candidate_timestamps(
    video_path: Path,
    interval: int,
    skip_scene_detect: bool = False,
) -> list[float]:
    """
    Merge scene-change timestamps with a fixed-interval grid.
    Returns a sorted, deduplicated list of timestamps.
    """
    duration = _video_duration(video_path)
    if duration <= 0:
        # Fallback: generate timestamps up to 4 hours
        duration = 4 * 3600

    logger.info("Video duration : %.1f s (%.1f min)", duration, duration / 60)

    if skip_scene_detect:
        logger.info("Scene detection skipped (--skip-scene-detect)")
        scene_ts: set[float] = set()
    else:
        scene_ts = set(_scene_change_timestamps(video_path))

    interval_ts = set(float(t) for t in range(0, int(duration), interval))

    all_ts = sorted(scene_ts | interval_ts)
    logger.info(
        "Candidate timestamps: %d scene-change + %d interval = %d total",
        len(scene_ts), len(interval_ts), len(all_ts),
    )
    return all_ts


# ─────────────────────────────────────────────────────────────────────────────
# Perceptual hash deduplication
# ─────────────────────────────────────────────────────────────────────────────

def _phash(image_path: Path):
    """Return perceptual hash of the image at *image_path*."""
    import imagehash  # type: ignore
    from PIL import Image  # type: ignore
    with Image.open(image_path) as img:
        return imagehash.phash(img)


def _is_new_visual(image_path: Path, last_hash, threshold: int) -> tuple[bool, any]:
    """
    Return (is_new, new_hash).
    *is_new* is True if the frame differs significantly from *last_hash*.
    """
    h = _phash(image_path)
    if last_hash is None:
        return True, h
    diff = abs(h - last_hash)
    return diff >= threshold, h


# ─────────────────────────────────────────────────────────────────────────────
# Frame upscaling
# ─────────────────────────────────────────────────────────────────────────────

def _upscale_to_jpeg_bytes(image_path: Path, min_width: int, quality: int) -> bytes:
    """
    Load image, upscale if narrower than *min_width*, return JPEG bytes.
    Uses LANCZOS resampling for sharpness (text/diagram friendly).
    """
    from PIL import Image  # type: ignore

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        if w < min_width:
            scale = min_width / w
            new_size = (min_width, int(h * scale))
            img = img.resize(new_size, Image.LANCZOS)
            logger.debug("  upscaled %dx%d → %dx%d", w, h, *new_size)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI vision call
# ─────────────────────────────────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """You are a technical visual analyst for an educational video.
Your ONLY job is to describe data-rich visual content that appears on screen.

DESCRIBE in detailed Markdown when you see:
- Slides, presentation decks (title, bullet points, key text)
- Code on screen (copy it verbatim inside a fenced code block with language tag)
- Terminal / shell output
- Diagrams, flowcharts, architecture diagrams (use Mermaid or ASCII art approximation)
- Charts, graphs, tables of data
- Whiteboards, hand-drawn diagrams

RESPOND with exactly: NO_VISUAL_DATA
…when the frame shows ONLY: a talking head, blank screen, plain background, B-roll footage,
countdown, or any frame where there is no educational data content worth capturing.

Keep your response concise but complete. Do not add commentary about the image quality."""

_VISION_USER_PROMPT = (
    "This frame is at timestamp {ts_str} in the video '{source}'.\n"
    "Describe any data-rich visual content present."
)


def _call_vision(
    client,
    model: str,
    image_bytes: bytes,
    timestamp: float,
    source_name: str,
    call_delay: float = API_CALL_DELAY,
) -> str | None:
    """
    Call OpenAI vision API. Returns the text response or None if NO_VISUAL_DATA.
    Respects *call_delay* seconds pacing and retries on 429 with exponential backoff.
    """
    import time

    b64 = base64.b64encode(image_bytes).decode()
    ts_str = _format_timestamp(timestamp)

    max_retries = 5
    backoff = 2.0

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS_REPLY,
                messages=[
                    {"role": "system", "content": _VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": _VISION_USER_PROMPT.format(
                                    ts_str=ts_str, source=source_name
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
            )
            # Honour pacing delay after a successful call
            time.sleep(call_delay)
            break  # success
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str or "rate_limit" in err_str.lower():
                wait = backoff * (2 ** attempt)
                logger.warning("  [%s] 429 rate-limit — waiting %.1fs (attempt %d/%d)",
                               ts_str, wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            logger.error("  Vision API call failed at %s: %s", ts_str, exc)
            return None
    else:
        logger.error("  [%s] gave up after %d retries", ts_str, max_retries)
        return None

    text = response.choices[0].message.content.strip()
    if "NO_VISUAL_DATA" in text:
        return None
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────────────────────

def _format_timestamp(seconds: float) -> str:
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _build_markdown(source_name: str, visual_entries: list[dict]) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"source: {source_name}",
        f"converted: {now}",
        "agent: VideoVisionExtractor",
        "model: gpt-4o-mini",
        "---",
        "",
        f"# Visual Content: {source_name}",
        "",
        f"> Generated by `video_vision_extractor.py` — {len(visual_entries)} visual moment(s) captured.",
        "",
    ]

    for i, entry in enumerate(visual_entries, 1):
        ts = entry["timestamp_str"]
        desc = entry["description"]
        lines += [
            f"## Visual {i:03d} — [{ts}]",
            "",
            desc,
            "",
            "---",
            "",
        ]

    if not visual_entries:
        lines += [
            "> **No data-rich visual content detected.**",
            ">",
            "> Possible causes:",
            "> - The video is primarily a talking-head lecture with no slides/code.",
            "> - Frame resolution was too low even after upscaling.",
            "> - Try re-running with `--hash-threshold 5 --interval 5` for denser sampling.",
            "",
        ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction pipeline
# ─────────────────────────────────────────────────────────────────────────────

def extract_visual_content(
    video_path: Path,
    output_path: Path,
    hash_threshold: int = HASH_THRESHOLD,
    interval: int = INTERVAL_SECONDS,
    min_width: int = MIN_WIDTH,
    dry_run: bool = False,
    skip_scene_detect: bool = False,
    api_delay: float = API_CALL_DELAY,
) -> int:
    """
    Run the full extraction pipeline.

    Returns the number of visual entries written to *output_path*.
    """
    _check_deps()

    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).parent / ".env")

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_VISION_MODEL", VISION_MODEL)

    if not api_key or api_key == "your_key_here":
        if not dry_run:
            sys.exit("[ERROR] OPENAI_API_KEY is not set in .env — cannot call vision model.")
        logger.warning("OPENAI_API_KEY not set — dry-run only, no API calls will be made.")
        client = None  # type: ignore
    else:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key, base_url=base_url)

    logger.info("=== VideoVisionExtractor ===")
    logger.info("Video  : %s", video_path)
    logger.info("Output : %s", output_path)
    logger.info("Model  : %s", model)
    logger.info("Params : hash_threshold=%d  interval=%ds  min_width=%dpx  skip_scene=%s  api_delay=%.1fs",
                hash_threshold, interval, min_width, skip_scene_detect, api_delay)

    # ── 1. Collect candidate timestamps ──────────────────────────────────────
    candidates = _collect_candidate_timestamps(video_path, interval, skip_scene_detect)

    # ── 2. Extract frames into temp dir, deduplicate, call vision ─────────────
    visual_entries: list[dict] = []
    last_hash = None
    accepted = 0
    skipped_dup = 0
    skipped_no_data = 0
    errors = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fullmark_vision_") as tmp:
        tmp_dir = Path(tmp)

        for idx, ts in enumerate(candidates):
            frame_path = tmp_dir / f"frame_{idx:06d}.jpg"
            ts_str = _format_timestamp(ts)

            if not _extract_frame_at(video_path, ts, frame_path):
                logger.debug("  [%s] frame extraction failed — skipping", ts_str)
                errors += 1
                continue

            # ── Perceptual hash dedup ─────────────────────────────────────
            is_new, new_hash = _is_new_visual(frame_path, last_hash, hash_threshold)
            if not is_new:
                logger.debug("  [%s] duplicate frame — skipping", ts_str)
                skipped_dup += 1
                continue

            last_hash = new_hash
            accepted += 1
            logger.info("  [%s] unique visual detected (frame %d/%d, accepted=%d)",
                        ts_str, idx + 1, len(candidates), accepted)
            if dry_run:
                logger.info("    [dry-run] would send to vision API")
                continue

            # ── Upscale + encode ──────────────────────────────────────────
            try:
                img_bytes = _upscale_to_jpeg_bytes(frame_path, min_width, JPEG_QUALITY)
            except Exception as exc:
                logger.error("  [%s] image processing failed: %s", ts_str, exc)
                errors += 1
                continue

            # ── Vision API ────────────────────────────────────────────────
            description = _call_vision(client, model, img_bytes, ts, video_path.name,
                                        call_delay=api_delay)
            if description is None:
                logger.info("    → NO_VISUAL_DATA")
                skipped_no_data += 1
                continue

            logger.info("    → visual content captured (%d chars)", len(description))
            visual_entries.append({
                "timestamp": ts,
                "timestamp_str": ts_str,
                "description": description,
            })

    # ── 3. Write output ───────────────────────────────────────────────────────
    md = _build_markdown(video_path.name, visual_entries)
    output_path.write_text(md, encoding="utf-8")

    logger.info("")
    logger.info("=== Summary ===")
    logger.info("Candidates    : %d", len(candidates))
    logger.info("Unique visuals: %d  (duplicates skipped: %d)", accepted, skipped_dup)
    logger.info("No data frames: %d", skipped_no_data)
    logger.info("API errors    : %d", errors)
    logger.info("Entries saved : %d", len(visual_entries))
    logger.info("Output file   : %s", output_path)

    return len(visual_entries)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _default_output_path(video_path: Path) -> Path:
    """Derive default output path from video path and OUTPUT_DIR."""
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).parent / ".env")
    output_dir = Path(os.getenv("OUTPUT_DIR", "./output"))
    return output_dir / f"{video_path.stem}_Video.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract visual content from a video using OpenAI vision model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("video", help="Path to the input video file")
    parser.add_argument(
        "--output", "-o",
        help="Output Markdown file path (default: OUTPUT_DIR/<video_stem>_Video.md)",
    )
    parser.add_argument(
        "--hash-threshold", "-t", type=int, default=HASH_THRESHOLD,
        help=f"Perceptual hash Hamming distance threshold (default: {HASH_THRESHOLD}). "
             "Lower = more frames kept. Try 5 for dense mode.",
    )
    parser.add_argument(
        "--interval", "-i", type=int, default=INTERVAL_SECONDS,
        help=f"Fixed-interval fallback in seconds (default: {INTERVAL_SECONDS}s). "
             "Use 5 for dense sampling.",
    )
    parser.add_argument(
        "--min-width", "-w", type=int, default=MIN_WIDTH,
        help=f"Minimum frame width in px before upscaling (default: {MIN_WIDTH}px)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Extract and deduplicate frames but do NOT call the vision API.",
    )
    parser.add_argument(
        "--skip-scene-detect", action="store_true",
        help="Skip PySceneDetect (very fast — use only fixed-interval sampling). "
             "Recommended for long videos (>30 min).",
    )
    parser.add_argument(
        "--api-delay", type=float, default=API_CALL_DELAY,
        help=f"Seconds to wait between API calls (default: {API_CALL_DELAY}s). "
             "Increase if hitting 429 rate-limits.",
    )
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    if not video_path.exists():
        sys.exit(f"[ERROR] Video file not found: {video_path}")

    if args.output:
        output_path = Path(args.output).resolve()
    else:
        output_path = _default_output_path(video_path).resolve()

    n = extract_visual_content(
        video_path=video_path,
        output_path=output_path,
        hash_threshold=args.hash_threshold,
        interval=args.interval,
        min_width=args.min_width,
        dry_run=args.dry_run,
        skip_scene_detect=args.skip_scene_detect,
        api_delay=args.api_delay,
    )

    if n == 0 and not args.dry_run:
        print(
            "\nTIP: No visual content was captured.\n"
            "Try denser sampling:\n"
            f"  python {Path(__file__).name} \"{video_path}\" "
            "--hash-threshold 5 --interval 5\n"
        )


if __name__ == "__main__":
    main()
