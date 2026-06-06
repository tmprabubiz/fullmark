"""
fullmark_cli.py
----------------
Command-line interface for FullMark.

Usage:
    python fullmark_cli.py <source> [OPTIONS]
    python fullmark_cli.py --help

Examples:
    python fullmark_cli.py report.pdf
    python fullmark_cli.py https://example.com --output ./my_output
    python fullmark_cli.py ./docs/ --output ./output
    python fullmark_cli.py archive.zip
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
@click.argument("source")
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
@click.version_option(version="1.0.0", prog_name="FullMark")
def main(source: str, output: str | None, whisper_model: str | None, verbose: bool) -> None:
    """FullMark — Convert ANY source format into a perfect Markdown file.

    SOURCE can be a file path, a directory path, or a URL.

    \b
    Supported formats:
      Documents : PDF DOCX RTF TXT EPUB XLSX CSV ODS PPTX ODP IPYNB MSG EML
      Web       : HTTP/HTTPS URLs, HTML, RSS feeds, YouTube URLs
      Images    : JPG PNG BMP TIFF WebP SVG
      Video     : MP4 AVI MOV MKV WEBM
      Audio     : MP3 WAV M4A
      Archives  : ZIP
    """
    _setup_logging(verbose)
    log = logging.getLogger("fullmark.cli")

    # Apply CLI overrides to environment
    import os
    if output:
        os.environ["OUTPUT_DIR"] = output
    if whisper_model:
        os.environ["WHISPER_MODEL"] = whisper_model

    # Import here so env overrides are picked up
    from fullmark.orchestrator import Orchestrator
    from fullmark import AgentError

    try:
        orchestrator = Orchestrator(output_dir=output)
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
