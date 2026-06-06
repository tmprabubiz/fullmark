"""
fullmark_cli.py
----------------
Command-line interface for FullMark.

Usage:
    python fullmark_cli.py <source> [OPTIONS]
    python fullmark_cli.py                    # scans input/ folder automatically
    python fullmark_cli.py --help

Examples:
    python fullmark_cli.py report.pdf
    python fullmark_cli.py https://example.com --output ./my_output
    python fullmark_cli.py ./docs/ --output ./output
    python fullmark_cli.py archive.zip
    python fullmark_cli.py https://example.com/docs --follow-links --crawl-depth 2
    python fullmark_cli.py --skip-existing      # re-runs but skips already-done files
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)-8s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _is_github_url(url: str) -> bool:
    """Return True if url is a GitHub repo URL (routes to RepoAgent, not crawlable)."""
    return "github.com/" in url


def _prompt_follow_links(
    source: str,
    orchestrator,
    crawl_depth: int,
    crawl_delay: float,
    max_pages: int,
) -> list[tuple[str, str]]:
    """Interactive crawl prompt for regular web URLs.

    Asks whether to follow links, estimates job size, warns about large jobs.
    Falls back to single-page conversion when stdin is not a TTY.
    Returns list of (url, markdown) tuples.
    """
    click.echo(f"\nSource: {source}", err=True)
    click.echo("Single-page conversion by default (no link following).", err=True)

    # Non-interactive (piped / redirected): skip straight to single-page
    if not sys.stdin.isatty():
        return orchestrator.convert(source)

    if not click.confirm("Follow links on this page and convert multiple pages?", default=False):
        return orchestrator.convert(source)

    # User wants to crawl — estimate scope first
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse
        from fullmark.utils.crawler import LinkCrawler

        resp = requests.get(source, timeout=10, headers={"User-Agent": "FullMark/1.0"})
        soup = BeautifulSoup(resp.text, "lxml")
        domain = urlparse(source).netloc
        links = {
            urljoin(source, a["href"])
            for a in soup.find_all("a", href=True)
            if urlparse(urljoin(source, a["href"])).netloc == domain
        }
        est_pages = min(len(links) + 1, max_pages)
        est_minutes = est_pages * crawl_delay / 60
        click.echo(f"\nEstimated pages : ~{est_pages} (capped at --max-pages {max_pages})", err=True)
        click.echo(f"Estimated time  : ~{est_minutes:.1f} min at {crawl_delay}s delay", err=True)
        if est_pages >= 20:
            click.echo(
                "\n\u26a0  Large crawl detected. Consider running overnight to avoid\n"
                "   token-rate limits. Use --crawl-delay 5 or higher. "
                "Add --skip-existing to resume if interrupted.",
                err=True,
            )
        if not click.confirm("Proceed with crawl?", default=True):
            click.echo("Cancelled \u2014 running single-page conversion instead.", err=True)
            return orchestrator.convert(source)

        crawler = LinkCrawler(
            source, depth=crawl_depth, delay=crawl_delay, max_pages=max_pages
        )
        results: list[tuple[str, str]] = []
        for url, md in crawler.crawl():
            click.echo(f"  converted: {url}", err=True)
            results.append((url, md))
        return results

    except Exception as exc:
        click.echo(f"Crawl setup error: {exc} \u2014 falling back to single-page.", err=True)
        return orchestrator.convert(source)


@click.command(name="fullmark")
@click.argument("source", required=False, default=None)
@click.option(
    "--output", "-o",
    default=None,
    help="Output directory (overrides OUTPUT_DIR in .env). Default: ./output",
    metavar="DIR",
)
@click.option(
    "--whisper-model", "-w",
    default=None,
    help="Whisper model size: tiny|base|small|medium|large (default: base)",
    metavar="MODEL",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
@click.option(
    "--follow-links",
    is_flag=True,
    default=False,
    help="Follow all hyperlinks found on URL source(s) and convert each page.",
)
@click.option(
    "--crawl-depth",
    default=1,
    show_default=True,
    help="Number of link-hop levels to follow (requires --follow-links).",
    metavar="N",
    type=int,
)
@click.option(
    "--crawl-delay",
    default=2.0,
    show_default=True,
    help="Seconds to sleep between HTTP requests during crawl.",
    metavar="SECS",
    type=float,
)
@click.option(
    "--max-pages",
    default=50,
    show_default=True,
    help="Hard cap on total pages crawled per URL (requires --follow-links).",
    metavar="N",
    type=int,
)
@click.option(
    "--skip-existing",
    is_flag=True,
    default=False,
    help="Skip sources already recorded in conversion_log.json.",
)
@click.version_option(version="1.0.0", prog_name="FullMark")
def main(
    source: str | None,
    output: str | None,
    whisper_model: str | None,
    verbose: bool,
    follow_links: bool,
    crawl_depth: int,
    crawl_delay: float,
    max_pages: int,
    skip_existing: bool,
) -> None:
    """FullMark — Convert ANY source format into a perfect Markdown file.

    SOURCE can be a file path, a directory path, or a URL.
    Omit SOURCE to convert everything in the input/ folder.

    \b
    Supported formats:
      Documents : PDF DOCX RTF TXT EPUB XLSX CSV ODS PPTX ODP IPYNB MSG EML
      Web       : HTTP/HTTPS URLs, HTML, RSS feeds, YouTube URLs
      Images    : JPG PNG BMP TIFF WebP SVG
      Video     : MP4 AVI MOV MKV WEBM
      Audio     : MP3 WAV M4A
      Archives  : ZIP
      URL Lists : TXT / DOCX / XLSX / CSV files containing one URL per line/cell
                  (valid URLs are fetched; non-URL lines are reported as skipped)
    """
    import os
    from fullmark import AgentError
    from fullmark.orchestrator import Orchestrator

    _setup_logging(verbose)
    log = logging.getLogger("fullmark.cli")

    if output:
        os.environ["OUTPUT_DIR"] = output
    if whisper_model:
        os.environ["WHISPER_MODEL"] = whisper_model
    if skip_existing:
        os.environ["SKIP_EXISTING"] = "true"

    try:
        orchestrator = Orchestrator(output_dir=output)

        if source is None:
            input_dir = Path("input")
            if not input_dir.exists() or not any(input_dir.iterdir()):
                click.echo(
                    "No source given and input/ folder is empty.\n"
                    "Usage: fullmark <source>  or  place files in input/ and run fullmark",
                    err=True,
                )
                sys.exit(1)
            click.echo("No source given — scanning input/ folder …", err=True)
            results = orchestrator.convert_input_folder()

        elif follow_links and source.startswith(("http://", "https://")):
            from fullmark.utils.crawler import LinkCrawler
            crawler = LinkCrawler(
                base_url=source, depth=crawl_depth,
                delay=crawl_delay, max_pages=max_pages,
            )
            crawler.warn_token_budget()
            results: list[tuple[str, str]] = []
            for url, md in crawler.crawl():
                orchestrator._write(url, md, "web")
                results.append((url, md))
            orchestrator._meta_log.write_summary()

        elif source.startswith(("http://", "https://")) and not _is_github_url(source):
            results = _prompt_follow_links(
                source, orchestrator, crawl_depth, crawl_delay, max_pages
            )

        else:
            results = orchestrator.convert(source)

    except AgentError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        log.exception("Unexpected error")
        click.echo(f"Unexpected error: {exc}", err=True)
        sys.exit(2)

    if not results:
        click.echo("Warning: no output produced.", err=True)
        sys.exit(1)

    click.echo(f"Done — {len(results)} file(s) converted.", err=True)
    for src, _ in results:
        click.echo(f"  ✓  {src}", err=True)


if __name__ == "__main__":
    main()
