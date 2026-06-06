"""
tests/test_orchestrator.py
Tests for Orchestrator — routing logic and output writing.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fullmark.orchestrator import Orchestrator
from fullmark.utils.file_utils import detect_agent, safe_output_path


# ──────────────────────────────────────────────────────────────────────────────
# detect_agent
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectAgent:
    def test_pdf_routes_to_document(self):
        assert detect_agent(Path("report.pdf")) == "document"

    def test_docx_routes_to_document(self):
        assert detect_agent(Path("notes.docx")) == "document"

    def test_csv_routes_to_document(self):
        assert detect_agent(Path("data.csv")) == "document"

    def test_html_routes_to_web(self):
        assert detect_agent(Path("page.html")) == "web"

    def test_url_routes_to_web(self):
        assert detect_agent("https://example.com") == "web"

    def test_http_url_routes_to_web(self):
        assert detect_agent("http://example.com/page") == "web"

    def test_jpg_routes_to_image(self):
        assert detect_agent(Path("photo.jpg")) == "image"

    def test_png_routes_to_image(self):
        assert detect_agent(Path("diagram.png")) == "image"

    def test_svg_routes_to_image(self):
        assert detect_agent(Path("flow.svg")) == "image"

    def test_mp4_routes_to_video(self):
        assert detect_agent(Path("lecture.mp4")) == "video"

    def test_mp3_routes_to_video(self):
        assert detect_agent(Path("podcast.mp3")) == "video"

    def test_zip_routes_to_archive(self):
        assert detect_agent(Path("bundle.zip")) == "archive"

    def test_unknown_extension_returns_unknown(self):
        assert detect_agent(Path("file.xyz")) == "unknown"

    def test_case_insensitive_extension(self):
        assert detect_agent(Path("photo.JPG")) == "image"
        assert detect_agent(Path("report.PDF")) == "document"


# ──────────────────────────────────────────────────────────────────────────────
# safe_output_path
# ──────────────────────────────────────────────────────────────────────────────

class TestSafeOutputPath:
    def test_file_path(self, tmp_path):
        result = safe_output_path("report.pdf", tmp_path)
        assert result.name == "report.md"
        assert result.parent == tmp_path

    def test_url(self, tmp_path):
        result = safe_output_path("https://example.com/article", tmp_path)
        assert result.suffix == ".md"

    def test_sanitises_special_chars(self, tmp_path):
        result = safe_output_path("my file (2024).pdf", tmp_path)
        assert " " not in result.name
        assert "(" not in result.name


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator routing
# ──────────────────────────────────────────────────────────────────────────────

class TestOrchestratorRouting:
    def test_routes_url_to_web_agent(self, tmp_path):
        orch = Orchestrator(output_dir=tmp_path)
        with patch.object(orch, "_run_agent", return_value="# Web") as mock_run:
            orch.convert("https://example.com")
        mock_run.assert_called_once_with("web", "https://example.com")

    def test_routes_txt_to_document_agent(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        orch = Orchestrator(output_dir=tmp_path / "out")
        with patch.object(orch, "_run_agent", return_value="# Doc") as mock_run:
            orch.convert(f)
        mock_run.assert_called_once_with("document", f)

    def test_routes_jpg_to_image_agent(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake")
        orch = Orchestrator(output_dir=tmp_path / "out")
        with patch.object(orch, "_run_agent", return_value="# Image") as mock_run:
            orch.convert(f)
        mock_run.assert_called_once_with("image", f)

    def test_routes_mp4_to_video_agent(self, tmp_path):
        f = tmp_path / "video.mp4"
        f.write_bytes(b"fake")
        orch = Orchestrator(output_dir=tmp_path / "out")
        with patch.object(orch, "_run_agent", return_value="# Video") as mock_run:
            orch.convert(f)
        mock_run.assert_called_once_with("video", f)

    def test_unknown_file_skipped(self, tmp_path):
        f = tmp_path / "file.xyz"
        f.write_text("data")
        orch = Orchestrator(output_dir=tmp_path / "out")
        with patch.object(orch, "_run_agent") as mock_run:
            results = orch.convert(f)
        mock_run.assert_not_called()
        assert results == []


# ──────────────────────────────────────────────────────────────────────────────
# ZIP handling
# ──────────────────────────────────────────────────────────────────────────────

class TestZipHandling:
    def test_zip_unpacks_and_routes_contents(self, tmp_path):
        # Create a ZIP with a .txt file inside
        txt_content = b"Hello from zip"
        zip_path = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("notes.txt", txt_content)

        orch = Orchestrator(output_dir=tmp_path / "out")

        with patch.object(orch, "_run_agent", return_value="# Notes") as mock_run:
            results = orch.convert(zip_path)

        mock_run.assert_called()
        assert len(results) == 1

    def test_zip_agent_failure_is_skipped(self, tmp_path):
        """If an agent crashes on a zip entry, the rest should continue."""
        zip_path = tmp_path / "mixed.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("good.txt", b"good")
            zf.writestr("bad.pdf", b"bad")

        orch = Orchestrator(output_dir=tmp_path / "out")

        call_count = 0
        def side_effect(agent_name, source):
            nonlocal call_count
            call_count += 1
            if "bad" in str(source):
                raise Exception("simulated failure")
            return "# Good"

        with patch.object(orch, "_run_agent", side_effect=side_effect):
            results = orch.convert(zip_path)

        # Should still have 1 result (good.txt); bad.pdf was skipped
        assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Agent error resilience
# ──────────────────────────────────────────────────────────────────────────────

class TestAgentErrorResilience:
    def test_agent_crash_does_not_stop_directory_conversion(self, tmp_path):
        src_dir = tmp_path / "docs"
        src_dir.mkdir()
        (src_dir / "a.txt").write_text("file a")
        (src_dir / "b.txt").write_text("file b")

        orch = Orchestrator(output_dir=tmp_path / "out")

        call_count = 0
        def side_effect(agent_name, source):
            nonlocal call_count
            call_count += 1
            if "a.txt" in str(source):
                raise Exception("agent crash")
            return "# B"

        with patch.object(orch, "_run_agent", side_effect=side_effect):
            results = orch.convert(src_dir)

        # Only b.txt succeeds
        assert len(results) == 1
        assert call_count == 2
