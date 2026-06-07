"""
fullmark/agents/video_agent.py
-------------------------------
Handles: MP4, AVI, MOV, MKV, WEBM (video), MP3, WAV, M4A (audio-only)

Pipeline:
  - Audio-only → Whisper transcription → CompilerAgent structuring
  - Video      → extract audio → Whisper + scene detection → frame OCR → CompilerAgent
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from fullmark import AgentError
from fullmark.utils.markdown_utils import front_matter, heading

logger = logging.getLogger(__name__)

_AGENT_NAME  = "VideoAgent"
_WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
_FRAME_INTERVAL = float(os.getenv("VIDEO_FRAME_INTERVAL", "10"))   # seconds between frames

_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a"})


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class FrameData:
    timestamp: float
    path: Path
    ocr_text: str = ""


class VideoAgent:
    """
    Convert video/audio files to Markdown using Whisper + scene detection + OCR.
    """

    def convert(self, source: str | Path) -> str:
        """
        Convert *source* video or audio file to a Markdown string.

        Args:
            source: Path to the video/audio file.

        Returns:
            Markdown string with YAML front matter.

        Raises:
            AgentError: If the file cannot be processed.
        """
        path = Path(source)
        if not path.exists():
            raise AgentError(f"File not found: {path}")

        self._check_ffmpeg()

        ext = path.suffix.lower()
        if ext in _AUDIO_EXTENSIONS:
            segments, frames = self._process_audio_only(path)
        else:
            segments, frames = self._process_video(path)

        from fullmark.agents.compiler_agent import CompilerAgent, CompilerInput
        compiler_input = CompilerInput(
            source=path.name,
            transcript=[{"start": s.start, "end": s.end, "text": s.text} for s in segments],
            frames=[{"timestamp": f.timestamp, "ocr_text": f.ocr_text, "path": str(f.path)} for f in frames],
        )
        body = CompilerAgent().compile(compiler_input)
        fmt_label = "Audio Transcription" if ext in _AUDIO_EXTENSIONS else "Video Transcription"
        if not body.lstrip().startswith("#"):
            body = f"## {fmt_label}: {path.name}\n\n{body}"
        fm = front_matter(path.name, _AGENT_NAME)
        return f"{fm}\n\n{body}"

    # ──────────────────────────────────────────────────────────────────────────
    # Audio-only
    # ──────────────────────────────────────────────────────────────────────────

    def _process_audio_only(self, path: Path) -> tuple[list[TranscriptSegment], list[FrameData]]:
        segments = self._transcribe(path)
        return segments, []

    # ──────────────────────────────────────────────────────────────────────────
    # Video
    # ──────────────────────────────────────────────────────────────────────────

    def _process_video(self, path: Path) -> tuple[list[TranscriptSegment], list[FrameData]]:
        with tempfile.TemporaryDirectory(prefix="fullmark_video_") as tmp:
            tmp_dir = Path(tmp)

            # 1. Extract audio
            audio_path = tmp_dir / "audio.wav"
            self._extract_audio(path, audio_path)

            # 2. Transcribe
            segments = self._transcribe(audio_path)

            # 3. Detect scene changes + extract frames
            frames = self._extract_frames(path, tmp_dir)

            # 4. OCR each frame
            for frame in frames:
                frame.ocr_text = self._ocr_frame(frame.path)

        return segments, frames

    # ──────────────────────────────────────────────────────────────────────────
    # Whisper transcription
    # ──────────────────────────────────────────────────────────────────────────

    def _transcribe(self, audio_path: Path) -> list[TranscriptSegment]:
        try:
            import whisper  # type: ignore
        except ImportError:
            logger.warning("openai-whisper not installed — no transcription")
            return []

        try:
            model = whisper.load_model(
                _WHISPER_MODEL,
                download_root=os.getenv("WHISPER_CACHE_DIR") or None,
            )
            result = model.transcribe(str(audio_path), word_timestamps=False)
        except Exception as exc:
            logger.error("Whisper transcription failed: %s", exc)
            return []

        segments: list[TranscriptSegment] = []
        for seg in result.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))
        return segments

    # ──────────────────────────────────────────────────────────────────────────
    # ffmpeg helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _check_ffmpeg(self) -> None:
        import shutil
        if not shutil.which("ffmpeg"):
            raise AgentError("ffmpeg not found on PATH — install ffmpeg to process video/audio")

    def _extract_audio(self, video_path: Path, output_path: Path) -> None:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise AgentError(
                f"ffmpeg audio extraction failed: {result.stderr.decode(errors='replace')}"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Scene detection + frame extraction
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_frames(self, video_path: Path, output_dir: Path) -> list[FrameData]:
        """
        Extract frames where slide/screen content changed, ignoring head motion.

        Primary strategy: sample every VIDEO_FRAME_INTERVAL seconds, crop out the
        likely webcam overlay region (top 20 % of height), run tesseract on the
        remaining content area, and keep the frame only when the OCR text differs
        meaningfully from the previous kept frame.  This makes human head movement
        invisible to the change detector while still catching every new slide.

        Fallback chain (if tesseract is not importable):
          1. PySceneDetect ContentDetector
          2. Fixed-interval sampling
        """
        frames = self._extract_frames_ocr_diff(video_path, output_dir)
        if frames is not None:          # tesseract was available
            return frames

        # ── PySceneDetect fallback ────────────────────────────────────────
        try:
            from scenedetect import open_video, SceneManager  # type: ignore
            from scenedetect.detectors import ContentDetector  # type: ignore
            video = open_video(str(video_path))
            manager = SceneManager()
            manager.add_detector(ContentDetector(threshold=27.0))
            manager.detect_scenes(video, show_progress=False)
            scene_list = manager.get_scene_list()
            result: list[FrameData] = []
            for i, (start_time, _) in enumerate(scene_list, 1):
                ts = start_time.get_seconds()
                frame_path = output_dir / f"frame-{i:03d}.jpg"
                if self._extract_frame_at(video_path, ts, frame_path):
                    result.append(FrameData(timestamp=ts, path=frame_path))
            if result:
                return result
        except Exception as exc:
            logger.warning("PySceneDetect unavailable or failed: %s — using fixed interval", exc)

        # ── Fixed-interval final fallback ─────────────────────────────────
        return self._extract_frames_fixed_interval(video_path, output_dir)

    def _extract_frames_ocr_diff(
        self, video_path: Path, output_dir: Path
    ) -> list[FrameData] | None:
        """
        Sample frames at VIDEO_FRAME_INTERVAL seconds.  For each frame, crop out
        the top 20 % of height (typical webcam/head overlay) and run tesseract on
        the remaining content region.  Only frames whose OCR text changed
        significantly compared to the previous kept frame are retained.

        Returns a list of FrameData, or None if tesseract is not importable (so
        the caller can try the next strategy).
        """
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError:
            return None

        duration = self._get_duration(video_path)
        if duration <= 0:
            return []

        frames: list[FrameData] = []
        prev_ocr: str = ""
        t = 0.0
        i = 1

        while t < duration:
            frame_path = output_dir / f"frame-{i:03d}.jpg"
            if self._extract_frame_at(video_path, t, frame_path):
                try:
                    with Image.open(frame_path) as img:
                        img = img.convert("RGB")
                        w, h = img.size
                        # Exclude top 20 % — webcam overlay is almost always in a
                        # top corner (top-left or top-right).
                        content_box = (0, int(h * 0.20), w, h)
                        cropped = img.crop(content_box)
                    curr_ocr = pytesseract.image_to_string(cropped).strip()
                    if self._ocr_changed(prev_ocr, curr_ocr):
                        frames.append(FrameData(timestamp=t, path=frame_path))
                        prev_ocr = curr_ocr
                    else:
                        # Discard duplicate frame to save disk space
                        try:
                            frame_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug("OCR diff check failed at t=%.1fs: %s", t, exc)
                    # Keep frame when we cannot judge — better to over-capture
                    frames.append(FrameData(timestamp=t, path=frame_path))

            t += _FRAME_INTERVAL
            i += 1

        logger.info("OCR-diff frame extraction: %d frames kept from %.0fs video", len(frames), duration)
        return frames

    @staticmethod
    def _ocr_changed(prev: str, curr: str, threshold: float = 0.70) -> bool:
        """
        Return True when the OCR text changed enough to indicate a new slide.

        Uses word-level Jaccard similarity.  A similarity below *threshold*
        (default 70 %) is considered a meaningful visual change.
        """
        if not prev:
            return bool(curr.strip())   # first frame that has any text is a change
        if not curr.strip():
            return False                # blank frame — not a useful new slide
        prev_words = set(prev.lower().split())
        curr_words = set(curr.lower().split())
        if not prev_words:
            return bool(curr_words)
        similarity = len(prev_words & curr_words) / len(prev_words | curr_words)
        return similarity < threshold

    def _extract_frames_fixed_interval(self, video_path: Path, output_dir: Path,
                                        interval_seconds: float = _FRAME_INTERVAL) -> list[FrameData]:
        """Extract one frame every *interval_seconds* as final fallback."""
        duration = self._get_duration(video_path)
        if duration <= 0:
            return []

        frames: list[FrameData] = []
        t = 0.0
        i = 1
        while t < duration:
            frame_path = output_dir / f"frame-{i:03d}.jpg"
            if self._extract_frame_at(video_path, t, frame_path):
                frames.append(FrameData(timestamp=t, path=frame_path))
            t += interval_seconds
            i += 1

        return frames

    def _get_duration(self, video_path: Path) -> float:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            return float(result.stdout.decode().strip())
        except Exception:
            return 0.0

    def _extract_frame_at(self, video_path: Path, timestamp: float, output: Path) -> bool:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return result.returncode == 0 and output.exists()

    # ──────────────────────────────────────────────────────────────────────────
    # OCR on frames
    # ──────────────────────────────────────────────────────────────────────────

    def _ocr_frame(self, frame_path: Path) -> str:
        """
        OCR a video frame.

        Upscales to >=1280px wide (LANCZOS) before running tesseract, then
        easyocr as a secondary fallback.  If both return empty text the frame
        is passed to the vision LLM chain (VISION_CHAIN in .env) as a last
        resort — same chain used by ImageAgent for decorative images.
        Set VISION_CHAIN= (empty) in .env to disable the vision fallback.
        """
        # ── Upscale helper ────────────────────────────────────────────────
        upscaled_path = frame_path
        try:
            from PIL import Image  # type: ignore
            MIN_WIDTH = 1280
            with Image.open(frame_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                if w < MIN_WIDTH:
                    scale = MIN_WIDTH / w
                    img = img.resize((MIN_WIDTH, int(h * scale)), Image.LANCZOS)
                    upscaled_path = frame_path.with_suffix(".upscaled.jpg")
                    img.save(upscaled_path, format="JPEG", quality=90)
        except Exception as exc:
            logger.debug("Upscale failed for %s: %s", frame_path.name, exc)

        # ── Tesseract ─────────────────────────────────────────────────────
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            with Image.open(upscaled_path) as img:
                text = pytesseract.image_to_string(img).strip()
            if text:
                return text
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("tesseract OCR failed on frame %s: %s", frame_path.name, exc)

        # ── EasyOCR fallback ──────────────────────────────────────────────
        try:
            import easyocr  # type: ignore
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            results = reader.readtext(str(upscaled_path), detail=0)
            text = " ".join(results).strip()
            if text:
                return text
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("easyocr failed on frame %s: %s", frame_path.name, exc)

        # ── Vision LLM last-resort fallback ───────────────────────────────
        # Only used when both OCR tools return empty — e.g. very low-res video,
        # hand-drawn diagrams, or decorative slides with no machine-readable text.
        # Controlled by VISION_CHAIN in .env (set to empty to disable).
        if os.getenv("VISION_CHAIN", "").strip():
            try:
                from fullmark.agents.image_agent import ImageAgent
                text = ImageAgent()._describe_with_vision(upscaled_path)
                if text:
                    logger.debug("Vision LLM described frame %s (%d chars)",
                                 frame_path.name, len(text))
                    return text
            except Exception as exc:
                logger.debug("Vision LLM fallback failed for %s: %s", frame_path.name, exc)

        return ""
