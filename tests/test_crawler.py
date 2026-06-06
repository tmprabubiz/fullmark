"""
tests/test_crawler.py
Tests for LinkCrawler — BFS crawl, depth control, delay, domain filtering,
exclude patterns.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fullmark.utils.crawler import LinkCrawler


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _mock_agent_convert(url: str) -> str:
    return f"# Page: {url}\n\nContent from {url}."


# ──────────────────────────────────────────────────────────────────────────────
# Basic crawl
# ──────────────────────────────────────────────────────────────────────────────

class TestCrawlBasic:
    @patch("fullmark.utils.crawler.time.sleep")
    def test_crawl_yields_start_url(self, mock_sleep):
        """Crawl with depth=0 yields only the start URL."""
        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=_mock_agent_convert):
            crawler = LinkCrawler("https://example.com", depth=0, delay=0)
            # depth=0 means: convert start URL only, don't follow links
            with patch.object(crawler, "_extract_links_from_url", return_value=[]):
                results = list(crawler.crawl())
        assert len(results) == 1
        url, md = results[0]
        assert url == "https://example.com"
        assert "Page: https://example.com" in md

    @patch("fullmark.utils.crawler.time.sleep")
    def test_crawl_depth_1_follows_links(self, mock_sleep):
        """Crawl with depth=1 follows one level of links."""
        child_url = "https://example.com/about"

        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=_mock_agent_convert):
            crawler = LinkCrawler("https://example.com", depth=1, delay=0, max_pages=10)

            def fake_extract(url):
                if url == "https://example.com":
                    return [child_url]
                return []

            with patch.object(crawler, "_extract_links_from_url", side_effect=fake_extract):
                results = list(crawler.crawl())

        urls = [r[0] for r in results]
        assert "https://example.com" in urls
        assert child_url in urls
        assert len(results) == 2

    @patch("fullmark.utils.crawler.time.sleep")
    def test_crawl_respects_max_pages(self, mock_sleep):
        """Crawl stops at max_pages even when more links exist."""
        links = [f"https://example.com/page{i}" for i in range(20)]

        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=_mock_agent_convert):
            crawler = LinkCrawler("https://example.com", depth=1, delay=0, max_pages=3)
            with patch.object(crawler, "_extract_links_from_url", return_value=links):
                results = list(crawler.crawl())

        assert len(results) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────────────────────────────────────

class TestCrawlDedup:
    @patch("fullmark.utils.crawler.time.sleep")
    def test_visited_urls_not_crawled_twice(self, mock_sleep):
        """Same URL appearing multiple times is only crawled once."""
        duplicate_links = ["https://example.com/about"] * 5

        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=_mock_agent_convert):
            crawler = LinkCrawler("https://example.com", depth=1, delay=0, max_pages=20)
            with patch.object(crawler, "_extract_links_from_url", return_value=duplicate_links):
                results = list(crawler.crawl())

        urls = [r[0] for r in results]
        assert urls.count("https://example.com/about") == 1


# ──────────────────────────────────────────────────────────────────────────────
# Exclude patterns
# ──────────────────────────────────────────────────────────────────────────────

class TestCrawlExcludePatterns:
    @patch("fullmark.utils.crawler.time.sleep")
    def test_excluded_url_skipped(self, mock_sleep):
        """URLs matching an exclude pattern are never crawled."""
        crawler = LinkCrawler(
            "https://example.com",
            depth=1,
            delay=0,
            exclude_patterns=[r"/login", r"/admin"],
        )
        assert crawler._is_excluded("https://example.com/login") is True
        assert crawler._is_excluded("https://example.com/admin/panel") is True
        assert crawler._is_excluded("https://example.com/about") is False

    @patch("fullmark.utils.crawler.time.sleep")
    def test_excluded_links_not_yielded(self, mock_sleep):
        """Links matching an exclude pattern are not processed during crawl."""
        links = ["https://example.com/login", "https://example.com/about"]

        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=_mock_agent_convert):
            crawler = LinkCrawler(
                "https://example.com",
                depth=1,
                delay=0,
                max_pages=10,
                exclude_patterns=[r"/login"],
            )
            with patch.object(crawler, "_extract_links_from_url", return_value=links):
                results = list(crawler.crawl())

        urls = [r[0] for r in results]
        assert "https://example.com/login" not in urls
        assert "https://example.com/about" in urls


# ──────────────────────────────────────────────────────────────────────────────
# Same-domain filtering
# ──────────────────────────────────────────────────────────────────────────────

class TestSameDomainFilter:
    def test_extract_links_filters_external_domains(self):
        """_extract_links_from_url returns only same-domain links when same_domain=True."""
        html = """
        <html><body>
        <a href="/internal">Internal</a>
        <a href="https://example.com/page">Same domain</a>
        <a href="https://other.com/page">External</a>
        </body></html>
        """

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            crawler = LinkCrawler("https://example.com", same_domain=True)
            links = crawler._extract_links_from_url("https://example.com")

        for link in links:
            assert "other.com" not in link

    def test_extract_links_allows_external_when_same_domain_false(self):
        """_extract_links_from_url includes external links when same_domain=False."""
        html = """
        <html><body>
        <a href="https://other.com/page">External</a>
        </body></html>
        """
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            crawler = LinkCrawler("https://example.com", same_domain=False)
            links = crawler._extract_links_from_url("https://example.com")

        assert any("other.com" in link for link in links)


# ──────────────────────────────────────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────────────────────────────────────

class TestCrawlErrorHandling:
    @patch("fullmark.utils.crawler.time.sleep")
    def test_agent_error_skipped_continues_crawl(self, mock_sleep):
        """AgentError on one page is logged and skipped; crawl continues."""
        from fullmark import AgentError

        call_count = [0]

        def agent_convert(url):
            call_count[0] += 1
            if "bad" in url:
                raise AgentError("test error")
            return f"# {url}"

        links = ["https://example.com/bad", "https://example.com/good"]

        with patch("fullmark.agents.web_agent.WebAgent.convert", side_effect=agent_convert):
            crawler = LinkCrawler("https://example.com", depth=1, delay=0, max_pages=5)
            with patch.object(crawler, "_extract_links_from_url", return_value=links):
                results = list(crawler.crawl())

        urls = [r[0] for r in results]
        assert "https://example.com/good" in urls
        assert "https://example.com/bad" not in urls


# ──────────────────────────────────────────────────────────────────────────────
# Token budget warning
# ──────────────────────────────────────────────────────────────────────────────

class TestWarnTokenBudget:
    def test_warn_token_budget_does_not_raise(self, capsys):
        crawler = LinkCrawler("https://example.com", depth=1, max_pages=10)
        crawler.warn_token_budget()  # should not raise
        captured = capsys.readouterr()
        assert "tokens" in captured.err.lower() or "crawl" in captured.err.lower()
