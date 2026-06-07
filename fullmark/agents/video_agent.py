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
        """Detect scene changes and extract one frame per scene."""
        try:
            from scenedetect import open_video, SceneManager  # type: ignore
            from scenedetect.detectors import ContentDetector  # type: ignore
        except ImportError:
            logger.warning("PySceneDetect not installed — falling back to fixed-interval frames")
            return self._extract_frames_fixed_interval(video_path, output_dir)

        try:
            video = open_video(str(video_path))
            manager = SceneManager()
            manager.add_detector(ContentDetector(threshold=27.0))
            manager.detect_scenes(video, show_progress=False)
            scene_list = manager.get_scene_list()
        except Exception as exc:
            logger.warning("Scene detection failed: %s — using fixed interval", exc)
            return self._extract_frames_fixed_interval(video_path, output_dir)

        frames: list[FrameData] = []
        for i, (start_time, _) in enumerate(scene_list, 1):
            timestamp = start_time.get_seconds()
            frame_path = output_dir / f"frame-{i:03d}.jpg"
            if self._extract_frame_at(video_path, timestamp, frame_path):
                frames.append(FrameData(timestamp=timestamp, path=frame_path))

        return frames

    def _extract_frames_fixed_interval(self, video_path: Path, output_dir: Path,
                                        interval_seconds: float = _FRAME_INTERVAL) -> list[FrameData]:
        """Extract one frame every *interval_seconds* as fallback."""
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

        Video frames are typically low-resolution compressed JPEGs.
        Upscaling to at least 1280px wide before OCR dramatically improves
        tesseract accuracy on slide/screen-recording content.
        Tries tesseract first, then easyocr as fallback.
        """
        try:
            from PIL import Image  # type: ignore
            from io import BytesIO

            MIN_WIDTH = 1280
            with Image.open(frame_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                if w < MIN_WIDTH:
                    scale = MIN_WIDTH / w
                    img = img.resize((MIN_WIDTH, int(h * scale)), Image.LANCZOS)
                # Write upscaled copy to a temp file for OCR tools
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=90)
                buf.seek(0)
                upscaled = Image.open(buf)

            import pytesseract  # type: ignore
            text = pytesseract.image_to_string(upscaled).strip()
            if text:
                return text
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("tesseract OCR failed on frame %s: %s", frame_path.name, exc)

        # Fallback: easyocr
        try:
            import easyocr  # type: ignore
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            results = reader.readtext(str(frame_path), detail=0)
            return " ".join(results)
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("easyocr failed on frame %s: %s", frame_path.name, exc)

        return ""
