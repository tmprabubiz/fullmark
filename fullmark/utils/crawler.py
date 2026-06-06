"""
fullmark/utils/crawler.py
--------------------------
Recursive URL crawler for FullMark.

Fetches a starting URL, extracts all anchor links, and optionally
follows them to a configurable depth — converting each page to Markdown
via WebAgent.

TOKEN BUDGET WARNING
--------------------
At ~120,000 chars per output file and ~4 chars per token, each page uses
roughly 30,000 tokens of LLM context.

A 50-page crawl with depth=2 could consume ~1.5 million tokens.
Plan accordingly — large crawls should be run overnight.
Use --crawl-delay (default 2s) to avoid portal rate-limit warnings.
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Iterator
from urllib.parse import urljoin, urldefrag, urlparse

logger = logging.getLogger(__name__)

_DEFAULT_DELAY: float = 2.0
_DEFAULT_MAX_PAGES: int = 50
_DEFAULT_DEPTH: int = 1

# Token budget constants
_CHARS_PER_TOKEN: int = 4
_CHARS_PER_FILE: int = 120_000
_TOKENS_PER_FILE: int = _CHARS_PER_FILE // _CHARS_PER_TOKEN  # ~30,000


class LinkCrawler:
    """
    Breadth-first link crawler that converts each discovered page to Markdown.

    Args:
        base_url: Starting URL.
        depth: How many link-hops to follow (0 = only start URL, no sub-links).
        delay: Seconds to sleep between HTTP requests (prevents rate limiting).
        max_pages: Hard cap on total pages processed.
        same_domain: If True, only follow links on the same hostname as base_url.
        exclude_patterns: List of regex strings — matching URLs are skipped.
    """

    def __init__(
        self,
        base_url: str,
        depth: int = _DEFAULT_DEPTH,
        delay: float = _DEFAULT_DELAY,
        max_pages: int = _DEFAULT_MAX_PAGES,
        same_domain: bool = True,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.depth = depth
        self.delay = delay
        self.max_pages = max_pages
        self.same_domain = same_domain
        self._base_parsed = urlparse(base_url)
        self._base_domain = self._base_parsed.netloc
        self._exclude_re = [re.compile(p, re.IGNORECASE) for p in (exclude_patterns or [])]
        self._visited: set[str] = set()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def warn_token_budget(self) -> None:
        """Print a token-budget warning before starting a crawl."""
        import sys

        # Conservative estimate: branching factor ~10 per hop
        est_pages = min(self.max_pages, 10 ** max(1, self.depth))
        est_tokens = est_pages * _TOKENS_PER_FILE

        logger.warning(
            "CRAWL BUDGET ESTIMATE: up to %d pages × ~%d tokens/page ≈ %d tokens total. "
            "Use --crawl-delay to pace requests.",
            est_pages, _TOKENS_PER_FILE, est_tokens,
        )
        print(
            f"\n  ⚠  Crawl estimate: up to {est_pages} pages × ~{_TOKENS_PER_FILE:,} tokens "
            f"= ~{est_tokens:,} tokens total.\n"
            f"     Depth={self.depth}, delay={self.delay}s, max_pages={self.max_pages}.\n"
            f"     Large sites: consider running overnight.\n"
            f"     Tip: start with --crawl-depth 1 --max-pages 10 to sample first.\n",
            file=sys.stderr,
        )

    def crawl(self) -> Iterator[tuple[str, str]]:
        """
        Crawl from *base_url* via BFS, yielding ``(url, markdown)`` pairs.

        Raises:
            Nothing — all per-URL errors are logged and skipped.
        """
        from fullmark.agents.web_agent import WebAgent
        from fullmark import AgentError

        agent = WebAgent()
        # Queue items: (url, current_depth)
        queue: deque[tuple[str, int]] = deque([(self.base_url, 0)])
        processed = 0

        while queue and processed < self.max_pages:
            url, current_depth = queue.popleft()
            url, _ = urldefrag(url)  # strip fragment (#section)
            url = url.rstrip("/")  # normalise trailing slash

            if url in self._visited:
                continue
            if self._is_excluded(url):
                logger.debug("Skipping excluded URL: %s", url)
                continue

            self._visited.add(url)

            # Sleep between requests (not before the very first one)
            if processed > 0 and self.delay > 0:
                logger.debug("Sleeping %.1fs", self.delay)
                time.sleep(self.delay)

            logger.info(
                "Crawling [depth=%d page=%d/%d]: %s",
                current_depth, processed + 1, self.max_pages, url,
            )

            try:
                markdown = agent.convert(url)
                processed += 1
                yield url, markdown

                # Enqueue sub-links if we haven't reached max depth
                if current_depth < self.depth:
                    for link in self._extract_links_from_url(url):
                        if link not in self._visited:
                            queue.append((link, current_depth + 1))

            except AgentError as exc:
                logger.warning("Skipping %s — agent error: %s", url, exc)
            except Exception as exc:
                logger.error("Skipping %s — unexpected error: %s", url, exc)

        logger.info("Crawl complete: %d/%d pages processed", processed, self.max_pages)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_links_from_url(self, url: str) -> list[str]:
        """
        Fetch *url* and extract all ``<a href>`` links.

        Returns a deduplicated list of absolute URLs on the same domain
        (if ``same_domain=True``).
        """
        import os
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            logger.debug("requests/bs4 not available — cannot extract links")
            return []

        timeout = int(os.getenv("WEB_REQUEST_TIMEOUT", "30"))
        user_agent = os.getenv(
            "WEB_USER_AGENT",
            "FullMark/1.0 (+https://github.com/tmprabubiz/fullmark)",
        )

        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.debug("Cannot fetch links from %s: %s", url, exc)
            return []

        links: list[str] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = str(a["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "javascript:", "tel:", "data:")):
                continue

            full_url = urljoin(url, href)
            full_url, _ = urldefrag(full_url)
            full_url = full_url.rstrip("/")

            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue
            if self.same_domain and parsed.netloc != self._base_domain:
                continue
            if full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

        logger.debug("Extracted %d links from %s", len(links), url)
        return links

    def _is_excluded(self, url: str) -> bool:
        """Return True if *url* matches any exclude pattern."""
        return any(p.search(url) for p in self._exclude_re)
