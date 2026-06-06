"""
tests/test_metadata_logger.py
Tests for MetadataLogger — recording, deduplication, summary writing.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fullmark.utils.metadata_logger import MetadataLogger


class TestRecord:
    def test_record_creates_json_log(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record(
            source="test.pdf",
            agent="document",
            output_files=[str(tmp_path / "test.md")],
            markdown="# Hello\n\nWorld",
        )
        log_path = tmp_path / "conversion_log.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["source"] == "test.pdf"
        assert data[0]["agent"] == "document"

    def test_record_captures_char_count(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        md = "# Title\n\nSome content here."
        logger.record("report.pdf", "document", [], md)
        log = json.loads((tmp_path / "conversion_log.json").read_text())
        assert log[0]["char_count"] == len(md)

    def test_record_captures_segments(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record(
            source="big.pdf",
            agent="document",
            output_files=["big_001.md", "big_002.md"],
            markdown="x" * 1000,
        )
        log = json.loads((tmp_path / "conversion_log.json").read_text())
        assert log[0]["segments"] == 2

    def test_record_appends_across_calls(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("a.pdf", "document", [], "# A")
        logger.record("b.pdf", "document", [], "# B")
        log = json.loads((tmp_path / "conversion_log.json").read_text())
        assert len(log) == 2
        sources = [e["source"] for e in log]
        assert "a.pdf" in sources
        assert "b.pdf" in sources

    def test_record_includes_content_hash(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("a.pdf", "document", [], "content")
        log = json.loads((tmp_path / "conversion_log.json").read_text())
        assert "content_hash" in log[0]
        assert len(log[0]["content_hash"]) == 16

    def test_record_includes_token_estimate(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        md = "x" * 400
        logger.record("a.pdf", "document", [], md)
        log = json.loads((tmp_path / "conversion_log.json").read_text())
        assert log[0]["token_estimate"] == 100  # 400 // 4


class TestAlreadyConverted:
    def test_new_source_not_already_converted(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        assert logger.already_converted("fresh.pdf") is None

    def test_recorded_source_detected_as_already_converted(self, tmp_path):
        """URL sources are hashed by URL string — same URL → same hash."""
        logger = MetadataLogger(tmp_path)
        url = "https://example.com/page"
        logger.record(url, "web", [], "# Page content")
        assert logger.already_converted(url) is not None

    def test_different_source_not_detected(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("https://example.com/a", "web", [], "# A")
        assert logger.already_converted("https://example.com/b") is None

    def test_already_converted_persists_across_instances(self, tmp_path):
        """Loading from existing JSON log should preserve dedup state."""
        logger1 = MetadataLogger(tmp_path)
        logger1.record("https://example.com/page", "web", [], "# Content")

        logger2 = MetadataLogger(tmp_path)  # second instance loads existing log
        assert logger2.already_converted("https://example.com/page") is not None


class TestWriteSummary:
    def test_summary_creates_markdown_file(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("doc.pdf", "document", [str(tmp_path / "doc.md")], "# Doc")
        logger.write_summary()
        summary = tmp_path / "conversion_log.md"
        assert summary.exists()

    def test_summary_contains_source_name(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("important.pdf", "document", [], "# Data")
        logger.write_summary()
        text = (tmp_path / "conversion_log.md").read_text(encoding="utf-8")
        assert "important.pdf" in text

    def test_summary_contains_agent_name(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.record("page.html", "web", [], "# Web page")
        logger.write_summary()
        text = (tmp_path / "conversion_log.md").read_text(encoding="utf-8")
        assert "web" in text

    def test_empty_log_summary_does_not_crash(self, tmp_path):
        logger = MetadataLogger(tmp_path)
        logger.write_summary()  # should not raise
        # File may or may not be written for empty log — just no crash
