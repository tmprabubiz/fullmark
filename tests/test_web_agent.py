"""
tests/test_web_agent.py
Tests for WebAgent and UrlListAgent — mocks all HTTP calls.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fullmark import AgentError
from fullmark.agents.web_agent import WebAgent, UrlListAgent


def _agent() -> WebAgent:
    return WebAgent()


# ──────────────────────────────────────────────────────────────────────────────
# Local HTML file
# ──────────────────────────────────────────────────────────────────────────────

class TestLocalHtml:
    def test_convert_local_html_returns_string(self, tmp_path):
        f = tmp_path / "page.html"
        f.write_text("<html><body><h1>Hello</h1><p>World</p></body></html>", encoding="utf-8")
        result = _agent().convert(f)
        assert isinstance(result, str)

    def test_convert_local_html_has_front_matter(self, tmp_path):
        f = tmp_path / "index.html"
        f.write_text("<html><body>Content</body></html>", encoding="utf-8")
        result = _agent().convert(f)
        assert "agent: WebAgent" in result
        assert "---" in result

    def test_convert_local_html_extracts_headings(self, tmp_path):
        f = tmp_path / "doc.html"
        f.write_text("<html><body><h1>Main Title</h1><p>Paragraph text.</p></body></html>")
        result = _agent().convert(f)
        assert "Main Title" in result

    def test_nonexistent_file_raises(self):
        with pytest.raises(AgentError, match="not found"):
            _agent().convert("/nonexistent/page.html")


# ──────────────────────────────────────────────────────────────────────────────
# URL fetching (mocked)
# ──────────────────────────────────────────────────────────────────────────────

class TestUrlFetch:
    def _mock_response(self, html: str, status: int = 200):
        resp = MagicMock()
        resp.text = html
        resp.status_code = status
        resp.raise_for_status = MagicMock()
        return resp

    def test_convert_url_calls_requests_get(self):
        html = "<html><body><h1>Remote Page</h1></body></html>"
        with patch("fullmark.agents.web_agent.WebAgent._fetch_url", return_value=html):
            result = _agent().convert("https://example.com")
        assert isinstance(result, str)

    def test_convert_url_has_front_matter(self):
        html = "<html><body><p>Content</p></body></html>"
        with patch("fullmark.agents.web_agent.WebAgent._fetch_url", return_value=html):
            result = _agent().convert("https://example.com/article")
        assert "agent: WebAgent" in result

    def test_fetch_error_raises_agent_error(self):
        with patch("fullmark.agents.web_agent.WebAgent._fetch_url",
                   side_effect=AgentError("connection refused")):
            with pytest.raises(AgentError):
                _agent().convert("https://bad-domain.invalid")


# ──────────────────────────────────────────────────────────────────────────────
# YouTube (mocked)
# ──────────────────────────────────────────────────────────────────────────────

class TestYoutube:
    def test_convert_youtube_returns_transcript(self):
        fake_transcript = [
            {"start": 0.0, "text": "Hello world"},
            {"start": 5.0, "text": "This is a test"},
        ]
        agent = _agent()
        with patch.object(agent, "_convert_youtube",
                          return_value="## YouTube Transcript\n\n[00:00] Hello world"):
            result = agent.convert("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert "Hello world" in result
        assert "00:00" in result

    def test_youtube_id_extraction(self):
        agent = _agent()
        assert agent._extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert agent._extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        assert agent._extract_youtube_id("https://example.com") is None

    def test_youtube_missing_transcript_raises(self):
        agent = _agent()
        with patch.object(agent, "_convert_youtube",
                          side_effect=AgentError("No transcript")):
            with pytest.raises(AgentError):
                agent.convert("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


# ──────────────────────────────────────────────────────────────────────────────
# RSS (mocked)
# ──────────────────────────────────────────────────────────────────────────────

class TestRss:
    def test_rss_detection(self):
        agent = _agent()
        assert agent._is_rss("<rss version='2.0'>") is True
        assert agent._is_rss("<html><body>") is False

    def test_convert_rss_returns_entries(self):
        agent = _agent()
        with patch.object(
            agent, "_convert_rss_url",
            return_value="# My Feed\n\n## 1. Entry 1\n\nSummary text.",
        ):
            with patch.object(agent, "_fetch_url", return_value="<rss></rss>"), \
                 patch.object(agent, "_is_rss", return_value=True):
                result = agent.convert("https://example.com/feed")
        assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# Section headings
# ──────────────────────────────────────────────────────────────────────────────

class TestSectionHeadings:
    def test_local_html_has_section_heading(self, tmp_path):
        f = tmp_path / "page.html"
        f.write_text("<html><body><p>content</p></body></html>", encoding="utf-8")
        result = WebAgent().convert(f)
        assert "## HTML File:" in result or "## Web Page:" in result or "##" in result

    def test_url_has_section_heading(self):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Hello</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = WebAgent().convert("https://example.com/page")
        assert "## Web Page:" in result


# ──────────────────────────────────────────────────────────────────────────────
# URL List Agent
# ──────────────────────────────────────────────────────────────────────────────

class TestUrlListAgent:
    def test_txt_file_extracts_urls(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://example.com\nhttps://test.org\nnot a url\n", encoding="utf-8")
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>content</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = UrlListAgent().convert(f)
        assert "https://example.com" in result
        assert "https://test.org" in result

    def test_skipped_lines_reported(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://example.com\nnot a url\njust text\n", encoding="utf-8")
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>x</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = UrlListAgent().convert(f)
        assert "Skipped Lines" in result
        assert "not a url" in result

    def test_url_count_in_output(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://a.com\nhttps://b.com\n", encoding="utf-8")
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>x</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = UrlListAgent().convert(f)
        assert "Total URLs found:** 2" in result

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(AgentError):
            UrlListAgent().convert(tmp_path / "missing.txt")

    def test_has_front_matter(self, tmp_path):
        f = tmp_path / "urls.txt"
        f.write_text("https://example.com\n", encoding="utf-8")
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>x</p></body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("requests.get", return_value=mock_resp):
            result = UrlListAgent().convert(f)
        assert "---" in result
        assert "agent: UrlListAgent" in result
