"""
tests/test_video_agent.py
Tests for VideoAgent — mocks ffmpeg, Whisper, and SceneDetect.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from fullmark import AgentError
from fullmark.agents.video_agent import VideoAgent, TranscriptSegment, FrameData


def _agent() -> VideoAgent:
    return VideoAgent()


# ──────────────────────────────────────────────────────────────────────────────
# ffmpeg check
# ──────────────────────────────────────────────────────────────────────────────

class TestFfmpegCheck:
    def test_raises_when_ffmpeg_missing(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake video")
        agent = _agent()
        with patch("shutil.which", return_value=None):
            with pytest.raises(AgentError, match="ffmpeg"):
                agent.convert(f)

    def test_nonexistent_file_raises(self):
        with pytest.raises(AgentError, match="not found"):
            _agent().convert("/nonexistent/video.mp4")


# ──────────────────────────────────────────────────────────────────────────────
# Audio-only (mp3/wav/m4a)
# ──────────────────────────────────────────────────────────────────────────────

class TestAudioOnly:
    def _fake_segments(self):
        return [
            TranscriptSegment(start=0.0, end=5.0, text="Hello world"),
            TranscriptSegment(start=5.0, end=10.0, text="This is a test"),
        ]

    def test_audio_convert_returns_markdown(self, tmp_path):
        f = tmp_path / "recording.mp3"
        f.write_bytes(b"fake audio")
        agent = _agent()

        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_transcribe", return_value=self._fake_segments()):
            result = agent.convert(f)

        assert isinstance(result, str)
        assert "---" in result
        assert "agent: VideoAgent" in result

    def test_audio_convert_includes_transcript_text(self, tmp_path):
        f = tmp_path / "talk.wav"
        f.write_bytes(b"fake audio")
        agent = _agent()

        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_transcribe", return_value=self._fake_segments()):
            result = agent.convert(f)

        assert "Hello world" in result

    def test_audio_empty_transcript_returns_no_content(self, tmp_path):
        f = tmp_path / "silent.wav"
        f.write_bytes(b"fake")
        agent = _agent()

        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_transcribe", return_value=[]):
            result = agent.convert(f)

        assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# Video processing (full pipeline, mocked)
# ──────────────────────────────────────────────────────────────────────────────

class TestVideoProcessing:
    def test_video_convert_returns_markdown(self, tmp_path):
        f = tmp_path / "lecture.mp4"
        f.write_bytes(b"fake video")
        agent = _agent()

        segments = [TranscriptSegment(start=0.0, end=30.0, text="Lecture content")]
        frames   = [FrameData(timestamp=0.0, path=tmp_path / "frame-001.jpg", ocr_text="Slide title")]

        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_process_video", return_value=(segments, frames)):
            result = agent.convert(f)

        assert isinstance(result, str)
        assert "VideoAgent" in result

    def test_video_convert_has_front_matter(self, tmp_path):
        f = tmp_path / "demo.mp4"
        f.write_bytes(b"fake")
        agent = _agent()

        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_process_video", return_value=([], [])):
            result = agent.convert(f)

        assert "source: demo.mp4" in result
        assert "agent: VideoAgent" in result


# ──────────────────────────────────────────────────────────────────────────────
# Compiler integration
# ──────────────────────────────────────────────────────────────────────────────

class TestCompilerIntegration:
    def test_compiler_called_with_transcript(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")
        agent = _agent()

        segments = [TranscriptSegment(start=0.0, end=5.0, text="Hello")]
        
        from fullmark.agents.compiler_agent import CompilerAgent
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
             patch.object(agent, "_process_video", return_value=(segments, [])), \
             patch.object(CompilerAgent, "compile", return_value="# Compiled output\n\nHello") as mock_compile:
            result = agent.convert(f)

        mock_compile.assert_called_once()
        assert "Compiled output" in result
