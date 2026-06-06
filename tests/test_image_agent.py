"""
tests/test_image_agent.py
Tests for ImageAgent — mocks all I/O and external tools.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fullmark import AgentError
from fullmark.agents.image_agent import ImageAgent


def _agent() -> ImageAgent:
    return ImageAgent()


# ──────────────────────────────────────────────────────────────────────────────
# Raster images
# ──────────────────────────────────────────────────────────────────────────────

class TestRaster:
    def test_convert_returns_string(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake jpeg")
        agent = _agent()
        with patch.object(agent, "_ocr_tesseract", return_value="Sample text here"):
            result = agent.convert(f)
        assert isinstance(result, str)

    def test_convert_has_front_matter(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"fake png")
        agent = _agent()
        with patch.object(agent, "_ocr_tesseract", return_value="text"):
            result = agent.convert(f)
        assert "agent: ImageAgent" in result
        assert "---" in result

    def test_ocr_text_in_output(self, tmp_path):
        f = tmp_path / "scan.png"
        f.write_bytes(b"fake")
        agent = _agent()
        with patch.object(agent, "_ocr_tesseract", return_value="Invoice total: $100"):
            result = agent.convert(f)
        assert "Invoice total: $100" in result

    def test_decorative_image_embeds_base64(self, tmp_path):
        """When OCR finds nothing, decorative image should be base64-embedded."""
        f = tmp_path / "logo.png"
        f.write_bytes(b"fake")
        agent = _agent()
        with patch.object(agent, "_ocr_tesseract", return_value=""), \
             patch.object(agent, "_ocr_easyocr", return_value=""), \
             patch.object(agent, "_embed_decorative", return_value="![logo](data:image/jpeg;base64,abc)"):
            result = agent.convert(f)
        assert "data:image/jpeg;base64" in result

    def test_nonexistent_file_raises(self):
        with pytest.raises(AgentError, match="not found"):
            _agent().convert("/nonexistent/image.jpg")

    def test_easyocr_fallback_called_when_tesseract_empty(self, tmp_path):
        f = tmp_path / "img.jpg"
        f.write_bytes(b"fake")
        agent = _agent()
        with patch.object(agent, "_ocr_tesseract", return_value="") as mock_tess, \
             patch.object(agent, "_ocr_easyocr", return_value="EasyOCR text") as mock_easy, \
             patch.object(agent, "_exif_meta", return_value=None):
            result = agent.convert(f)
        mock_easy.assert_called_once()
        assert "EasyOCR text" in result


# ──────────────────────────────────────────────────────────────────────────────
# Table detection
# ──────────────────────────────────────────────────────────────────────────────

class TestTableDetection:
    def test_detects_table_from_aligned_text(self):
        agent = _agent()
        text = "Name    Age    City\nAlice   30     NYC\nBob     25     LA"
        result = agent._try_table_detection(text)
        assert "| Name |" in result or "Name" in result

    def test_single_column_not_table(self):
        agent = _agent()
        text = "Line one\nLine two\nLine three"
        result = agent._try_table_detection(text)
        assert result == ""

    def test_empty_text_not_table(self):
        agent = _agent()
        assert agent._try_table_detection("") == ""


# ──────────────────────────────────────────────────────────────────────────────
# SVG
# ──────────────────────────────────────────────────────────────────────────────

class TestSvg:
    def test_convert_svg_returns_string(self, tmp_path):
        svg_content = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">
  <rect x="10" y="10" width="80" height="40"/>
  <text x="20" y="35">Start</text>
  <line x1="90" y1="30" x2="110" y2="30"/>
  <rect x="110" y="10" width="80" height="40"/>
  <text x="120" y="35">End</text>
</svg>"""
        f = tmp_path / "diagram.svg"
        f.write_text(svg_content, encoding="utf-8")
        result = _agent().convert(f)
        assert isinstance(result, str)

    def test_convert_svg_has_front_matter(self, tmp_path):
        f = tmp_path / "flow.svg"
        f.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
        result = _agent().convert(f)
        assert "agent: ImageAgent" in result

    def test_convert_svg_generates_mermaid(self, tmp_path):
        svg_content = """<svg xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="50" height="20"/>
  <text>NodeA</text>
  <rect x="100" y="0" width="50" height="20"/>
  <text>NodeB</text>
</svg>"""
        f = tmp_path / "graph.svg"
        f.write_text(svg_content)
        result = _agent().convert(f)
        # Should contain mermaid block or text content
        assert "NodeA" in result or "mermaid" in result


# ──────────────────────────────────────────────────────────────────────────────
# Section headings
# ──────────────────────────────────────────────────────────────────────────────

class TestSectionHeadings:
    def test_raster_has_section_heading(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake jpeg")
        with patch.object(ImageAgent, "_ocr_tesseract", return_value="some text"), \
             patch.object(ImageAgent, "_exif_meta", return_value=None):
            result = _agent().convert(f)
        assert "##" in result

    def test_svg_has_section_heading(self, tmp_path):
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>Hello</text></svg>'
        f = tmp_path / "diagram.svg"
        f.write_text(svg)
        with patch.object(ImageAgent, "_exif_meta", return_value=None):
            result = _agent().convert(f)
        assert "##" in result


# ──────────────────────────────────────────────────────────────────────────────
# Vision LLM fallback
# ──────────────────────────────────────────────────────────────────────────────

class TestVisionFallback:
    def test_vision_llm_called_when_no_ocr_text(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake jpeg")
        with patch.object(ImageAgent, "_ocr_tesseract", return_value=""), \
             patch.object(ImageAgent, "_ocr_easyocr", return_value=""), \
             patch.object(ImageAgent, "_describe_with_vision", return_value="A dog in a park.") as mock_vis, \
             patch.object(ImageAgent, "_exif_meta", return_value=None):
            result = _agent().convert(f)
        mock_vis.assert_called_once()
        assert "A dog in a park." in result

    def test_base64_fallback_when_vision_returns_none(self, tmp_path):
        import io
        from PIL import Image as PILImage
        img = PILImage.new("RGB", (10, 10), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        f = tmp_path / "photo.jpg"
        f.write_bytes(buf.getvalue())
        with patch.object(ImageAgent, "_ocr_tesseract", return_value=""), \
             patch.object(ImageAgent, "_ocr_easyocr", return_value=""), \
             patch.object(ImageAgent, "_describe_with_vision", return_value=""), \
             patch.object(ImageAgent, "_exif_meta", return_value=None):
            result = _agent().convert(f)
        # Should fall back to base64 embed
        assert "data:image" in result or "photo.jpg" in result

    def test_vision_description_has_heading(self, tmp_path):
        f = tmp_path / "chart.png"
        f.write_bytes(b"fake png")
        with patch.object(ImageAgent, "_ocr_tesseract", return_value=""), \
             patch.object(ImageAgent, "_ocr_easyocr", return_value=""), \
             patch.object(ImageAgent, "_describe_with_vision", return_value="## Chart\n\nBar chart showing sales."), \
             patch.object(ImageAgent, "_exif_meta", return_value=None):
            result = _agent().convert(f)
        assert "Chart" in result
