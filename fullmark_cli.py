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
    _setup_logging(verbose)
    log = logging.getLogger("fullmark.cli")

    import os
    if output:
        os.environ["OUTPUT_DIR"] = output
    if whisper_model:
        os.environ["WHISPER_MODEL"] = whisper_model
    if skip_existing:
        os.environ["SKIP_EXISTING"] = "true"

    from fullmark.orchestrator import Orchestrator
    from fullmark import AgentError

    try:
        orchestrator = Orchestrator(output_dir=output)

        # ── No-arg mode: scan input/ folder ─────────────────────────────────
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

        # ── Crawl mode: follow links from URL ────────────────────────────────
        elif follow_links and source.startswith(("http://", "https://")):
            from fullmark.utils.crawler import LinkCrawler

            crawler = LinkCrawler(
                base_url=source,
                depth=crawl_depth,
                delay=crawl_delay,
                max_pages=max_pages,
            )
            crawler.warn_token_budget()

            results: list[tuple[str, str]] = []
            for url, md in crawler.crawl():
                orchestrator._write(url, md, "web")
                results.append((url, md))
            orchestrator._meta_log.write_summary()

        # ── Normal mode ───────────────────────────────────────────────────────
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
