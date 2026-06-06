"""
fullmark/agents/web_agent.py
-----------------------------
Handles: HTTP/HTTPS URLs, local HTML files, RSS feeds, YouTube URLs,
         and URL-list files (.txt, .docx, .doc, spreadsheets).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

from dotenv import load_dotenv

from fullmark import AgentError
from fullmark.utils.markdown_utils import clean_text, front_matter, heading

load_dotenv()
logger = logging.getLogger(__name__)

_AGENT_NAME = "WebAgent"
_DEFAULT_TIMEOUT = int(os.getenv("WEB_REQUEST_TIMEOUT", "30"))
_USER_AGENT = os.getenv(
    "WEB_USER_AGENT",
    "FullMark/1.0 (+https://github.com/tmprabubiz/fullmark)",
)
_YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}


class WebAgent:
    """
    Convert web sources (URLs, HTML files, RSS feeds, YouTube) to Markdown.
    """

    def convert(self, source: str | Path) -> str:
        """
        Convert *source* to a Markdown string.

        Args:
            source: A URL string or path to a local HTML file.

        Returns:
            Markdown string with YAML front matter.

        Raises:
            AgentError: If the source cannot be fetched or parsed.
        """
        source_str = str(source)

        if source_str.startswith(("http://", "https://")):
            parsed = urlparse(source_str)
            if parsed.netloc in _YOUTUBE_DOMAINS:
                body = self._convert_youtube(source_str)
                fmt_label = "YouTube Video"
            else:
                html = self._fetch_url(source_str)
                if self._is_rss(html):
                    body = self._convert_rss_url(source_str)
                    fmt_label = "RSS Feed"
                else:
                    body = self._convert_html(html, base_url=source_str)
                    fmt_label = "Web Page"
        else:
            path = Path(source_str)
            if not path.exists():
                raise AgentError(f"File not found: {path}")
            html = path.read_text(encoding="utf-8", errors="replace")
            body = self._convert_html(html, base_url=path.as_uri())
            fmt_label = "HTML File"

        if not body.lstrip().startswith("#"):
            body = f"## {fmt_label}: {source_str}\n\n{body}"

        fm = front_matter(source_str, _AGENT_NAME)
        return f"{fm}\n\n{body}"

    # ──────────────────────────────────────────────────────────────────────────
    # Fetch
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_url(self, url: str) -> str:
        try:
            import requests  # type: ignore
        except ImportError:
            raise AgentError("requests not installed — cannot fetch URLs")
        try:
            resp = requests.get(
                url,
                timeout=_DEFAULT_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            raise AgentError(f"Failed to fetch {url}: {exc}") from exc

    def _is_rss(self, html: str) -> bool:
        return bool(re.search(r"<(rss|feed|atom)[^>]*>", html[:2000], re.IGNORECASE))

    # ──────────────────────────────────────────────────────────────────────────
    # HTML → Markdown
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_html(self, html: str, base_url: str = "") -> str:
        try:
            from markdownify import markdownify as md  # type: ignore
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError:
            raise AgentError("markdownify or beautifulsoup4 not installed")

        soup = BeautifulSoup(html, "lxml")

        # Remove nav, footer, scripts, styles — keep content
        for tag in soup.find_all(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()

        # Handle images — download if AUTO_DOWNLOAD_IMAGES and base_url is http
        image_contents: dict[str, str] = {}
        if os.getenv("AUTO_DOWNLOAD_IMAGES", "true").lower() == "true" and base_url.startswith("http"):
            image_contents = self._collect_images(soup, base_url)

        # Convert to Markdown
        content = str(soup)
        markdown = md(content, heading_style="ATX", bullets="-", strip=["a"])
        markdown = clean_text(markdown)

        # Replace image file references with content extracted by ImageAgent
        if image_contents:
            import re as _re
            for filename, img_md in image_contents.items():
                if img_md:
                    # Strip YAML front matter from ImageAgent output
                    body = img_md.split("---\n\n", 1)[-1].strip()
                    if body:
                        markdown = _re.sub(
                            r'!\[[^\]]*\]\(' + _re.escape(filename) + r'\)',
                            f"\n\n{body}\n\n",
                            markdown,
                        )

        return markdown

    def _collect_images(self, soup, base_url: str) -> dict[str, str]:
        """Download <img> tags, run ImageAgent on each; return {filename: md_content}."""
        try:
            import requests  # type: ignore
        except ImportError:
            return {}

        # Prefer the per-conversion image dir set by the orchestrator
        output_dir = Path(os.getenv("FULLMARK_IMAGE_DIR") or os.getenv("OUTPUT_DIR", "./output"))
        output_dir.mkdir(parents=True, exist_ok=True)

        counter = 1
        results: dict[str, str] = {}
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if not src or src.startswith("data:"):
                continue
            # Skip tiny tracking pixels
            try:
                w = int(img.get("width", 999))
                h = int(img.get("height", 999))
                if w < 5 or h < 5:
                    continue
            except (ValueError, TypeError):
                pass

            img_url = urljoin(base_url, src)
            try:
                resp = requests.get(
                    img_url,
                    timeout=10,
                    headers={"User-Agent": _USER_AGENT},
                )
                resp.raise_for_status()

                # Determine real extension from Content-Type or content sniff
                ct = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                _MIME_EXT = {
                    "image/svg+xml": ".svg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                    "image/bmp": ".bmp",
                    "image/tiff": ".tiff",
                    "image/jpeg": ".jpg",
                }
                ext = _MIME_EXT.get(ct, "")
                if not ext:
                    # Sniff first bytes
                    head = resp.content[:16]
                    if head[:4] in (b'\x89PNG', b'GIF8') or head[:2] == b'BM':
                        ext = {b'\x89PNG': ".png", b'GIF8': ".gif", b'BM': ".bmp"}[head[:4] if head[:4] in (b'\x89PNG', b'GIF8') else head[:2]]
                    elif head[:2] in (b'\xff\xd8',):
                        ext = ".jpg"
                    elif b"<svg" in head or b"<?xml" in head:
                        ext = ".svg"
                    else:
                        ext = ".jpg"  # fallback

                filename = f"image-{counter:03d}{ext}"
                dest = output_dir / filename
                dest.write_bytes(resp.content)
                img["src"] = filename
                counter += 1
                logger.debug("downloaded %s → %s", img_url, filename)
                # Extract content from the image via ImageAgent (OCR / vision / embed)
                try:
                    from fullmark.agents.image_agent import ImageAgent
                    results[filename] = ImageAgent().convert(dest)
                except Exception as img_exc:
                    logger.debug("ImageAgent skipped %s: %s", filename, img_exc)
                    results[filename] = ""
            except Exception as exc:
                logger.debug("skipped image %s: %s", img_url, exc)

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # RSS / Atom feeds
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_rss_url(self, url: str) -> str:
        try:
            import feedparser  # type: ignore
        except ImportError:
            raise AgentError("feedparser not installed — cannot parse RSS")

        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            raise AgentError(f"Failed to parse RSS feed: {url}")

        parts = [heading(feed.feed.get("title", "RSS Feed"), 1), ""]
        for i, entry in enumerate(feed.entries, 1):
            title   = entry.get("title", f"Entry {i}")
            link    = entry.get("link", "")
            summary = clean_text(entry.get("summary", ""))
            date    = entry.get("published", "")
            parts.append(f"## {i}. {title}")
            if date:
                parts.append(f"*{date}*")
            if link:
                parts.append(f"[Read more]({link})")
            if summary:
                parts.append(summary)
            parts.append("")

        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────────
    # YouTube
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_youtube(self, url: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
            from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound  # type: ignore
        except ImportError:
            raise AgentError("youtube-transcript-api not installed")

        video_id = self._extract_youtube_id(url)
        if not video_id:
            raise AgentError(f"Cannot extract video ID from YouTube URL: {url}")

        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        except (TranscriptsDisabled, NoTranscriptFound) as exc:
            raise AgentError(f"No transcript for {url}: {exc}") from exc
        except Exception as exc:
            raise AgentError(f"YouTube transcript fetch failed for {url}: {exc}") from exc

        parts = [
            heading(f"YouTube Transcript", 1),
            f"**URL:** {url}",
            f"**Video ID:** {video_id}",
            "",
            heading("Transcript", 2),
        ]

        for entry in transcript_list:
            start = entry.get("start", 0)
            text  = entry.get("text", "").strip()
            mins  = int(start) // 60
            secs  = int(start) % 60
            parts.append(f"[{mins:02d}:{secs:02d}] {text}")

        return "\n\n".join(parts)

    @staticmethod
    def _extract_youtube_id(url: str) -> str | None:
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# URL List Agent
# ──────────────────────────────────────────────────────────────────────────────

class UrlListAgent:
    """
    Process a file containing a list of URLs (.txt, .docx/.doc, or spreadsheet).

    Each valid URL is fetched and converted via ``WebAgent``.
    Lines that are not valid URLs are skipped and reported in the output.
    """

    def convert(self, source: str | Path) -> str:
        """
        Extract URLs from *source* file and convert each one to Markdown.

        Args:
            source: Path to a .txt, .docx, .doc, .xlsx, .xls, .ods, or .csv
                    file containing URLs (one per line / cell).

        Returns:
            Combined Markdown string with YAML front matter.

        Raises:
            AgentError: If the file cannot be read.
        """
        from fullmark.utils.file_utils import extract_urls_from_file

        path = Path(source)
        if not path.exists():
            raise AgentError(f"File not found: {path}")

        urls, skipped = extract_urls_from_file(path)

        if not urls and not skipped:
            raise AgentError(f"No content found in URL list file: {path.name}")

        fm = front_matter(path.name, "UrlListAgent")
        parts: list[str] = [fm, ""]

        parts.append(f"## URL List: {path.name}")
        parts.append(f"")
        parts.append(f"**Total URLs found:** {len(urls)}  ")
        parts.append(f"**Lines skipped (not a URL):** {len(skipped)}")
        parts.append("")

        if skipped:
            parts.append("## Skipped Lines")
            parts.append("")
            parts.append("The following lines were not recognised as URLs and were ignored:")
            parts.append("")
            for line in skipped:
                parts.append(f"- `{line}`")
            parts.append("")

        if not urls:
            parts.append("*No valid URLs found in this file.*")
            return "\n".join(parts)

        agent = WebAgent()
        for i, url in enumerate(urls, 1):
            parts.append(f"---")
            parts.append(f"")
            parts.append(f"## URL {i}: {url}")
            parts.append("")
            logger.info("UrlListAgent: converting URL %d/%d — %s", i, len(urls), url)
            try:
                md = agent.convert(url)
                # Strip front matter from individual URL results — already have one
                lines = md.splitlines()
                if lines and lines[0].strip() == "---":
                    try:
                        end = lines.index("---", 1)
                        md = "\n".join(lines[end + 1:]).lstrip()
                    except ValueError:
                        pass
                parts.append(md)
            except AgentError as exc:
                logger.warning("Failed to convert %s: %s", url, exc)
                parts.append(f"**Error:** Could not convert this URL — {exc}")
            parts.append("")

        return "\n".join(parts)
