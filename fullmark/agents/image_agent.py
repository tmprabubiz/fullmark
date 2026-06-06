"""
fullmark/agents/image_agent.py
-------------------------------
Handles: JPG, JPEG, PNG, BMP, TIFF, TIF, WebP, SVG
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fullmark import AgentError
from fullmark.utils.markdown_utils import (
    bytes_to_base64,
    clean_text,
    front_matter,
    heading,
    rows_to_gfm_table,
)

logger = logging.getLogger(__name__)

_AGENT_NAME = "ImageAgent"
_EMBED_DECORATIVE = os.getenv("EMBED_DECORATIVE_IMAGES", "true").lower() == "true"
_SVG_TO_MERMAID  = os.getenv("SVG_TO_MERMAID", "true").lower() == "true"


class ImageAgent:
    """
    Convert image files to Markdown.

    - Raster images: OCR → structured Markdown or base64-embedded decorative image.
    - SVG: parse → Mermaid diagram or text extraction.
    """

    def convert(self, source: str | Path) -> str:
        """
        Convert *source* image to a Markdown string.

        Args:
            source: Path to the image file.

        Returns:
            Markdown string with YAML front matter.

        Raises:
            AgentError: If the file cannot be read.
        """
        path = Path(source)
        if not path.exists():
            raise AgentError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext == ".svg":
            body = self._convert_svg(path)
            fmt_label = "SVG Diagram"
        else:
            body = self._convert_raster(path)
            fmt_label = "Image"

        if not body.lstrip().startswith("#"):
            body = f"## {fmt_label}: {path.name}\n\n{body}"

        fm = front_matter(path.name, _AGENT_NAME, extra=self._exif_meta(path))
        return f"{fm}\n\n{body}"

    # ──────────────────────────────────────────────────────────────────────────
    # Raster images
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_raster(self, path: Path) -> str:
        ocr_text = self._ocr_tesseract(path)
        if not ocr_text.strip():
            logger.debug("tesseract found no text in %s — trying easyocr", path.name)
            ocr_text = self._ocr_easyocr(path)

        if ocr_text.strip():
            table_md = self._try_table_detection(ocr_text)
            if table_md:
                return f"## Extracted Table\n\n{table_md}"
            return f"## Extracted Text\n\n{clean_text(ocr_text)}"

        # No OCR text — try vision LLM first, then base64 embed as last resort
        logger.debug("No OCR text in %s — trying vision LLM", path.name)
        vision_md = self._describe_with_vision(path)
        if vision_md:
            return f"## Image Description\n\n{vision_md}"

        if _EMBED_DECORATIVE:
            return self._embed_decorative(path)

        return f"*No text detected in {path.name}*"

    def _ocr_tesseract(self, path: Path) -> str:
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError:
            logger.debug("pytesseract or Pillow not installed")
            return ""
        try:
            img = Image.open(path)
            return pytesseract.image_to_string(img)
        except Exception as exc:
            logger.warning("tesseract OCR failed on %s: %s", path.name, exc)
            return ""

    def _ocr_easyocr(self, path: Path) -> str:
        try:
            import easyocr  # type: ignore
        except ImportError:
            logger.debug("easyocr not installed")
            return ""
        try:
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            results = reader.readtext(str(path), detail=0)
            return " ".join(results)
        except Exception as exc:
            logger.warning("easyocr failed on %s: %s", path.name, exc)
            return ""

    def _describe_with_vision(self, path: Path) -> str:
        """
        Send the image to a vision LLM and return a Markdown description.
        Returns empty string if no vision provider is available or call fails.
        """
        try:
            from PIL import Image as _PILImage  # type: ignore
            import io as _io

            img = _PILImage.open(path).convert("RGB")
            img.thumbnail((1024, 1024))  # cap size to stay within API limits
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            image_bytes = buf.getvalue()
        except Exception as exc:
            logger.debug("Cannot read image for vision LLM %s: %s", path.name, exc)
            return ""

        try:
            from fullmark.utils.model_client import ModelClient
            client = ModelClient()
            result = client.describe_image(image_bytes, mime_type="image/jpeg")
            return result or ""
        except Exception as exc:
            logger.debug("Vision LLM call failed for %s: %s", path.name, exc)
            return ""

    def _try_table_detection(self, text: str) -> str:
        """
        Heuristically detect if OCR text looks like a table and convert it.
        Returns a GFM table string, or empty string if not table-like.
        """
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return ""

        # Detect consistent column separation (2+ spaces or tabs)
        split_lines = [re.split(r"\s{2,}|\t", ln.strip()) for ln in lines]
        col_counts = [len(cols) for cols in split_lines]
        if not col_counts:
            return ""

        # Majority must have the same column count ≥ 2
        most_common_count = max(set(col_counts), key=col_counts.count)
        if most_common_count < 2:
            return ""
        consistent = sum(1 for c in col_counts if c == most_common_count)
        if consistent / len(col_counts) < 0.7:
            return ""

        headers = split_lines[0]
        rows    = [row for row in split_lines[1:] if len(row) == most_common_count]
        if not rows:
            return ""

        # Pad or trim to header length
        rows = [
            row[:len(headers)] + [""] * (len(headers) - len(row))
            for row in rows
        ]
        return rows_to_gfm_table(headers, rows)

    def _embed_decorative(self, path: Path) -> str:
        """Return a base64-embedded Markdown image."""
        try:
            from PIL import Image  # type: ignore
            import io as _io

            img = Image.open(path)
            # Resize to thumbnail for embedding
            img.thumbnail((800, 800))
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            data_uri = bytes_to_base64(buf.getvalue(), "image/jpeg")
            alt = path.stem.replace("_", " ").replace("-", " ")
            return f"![{alt}]({data_uri})"
        except Exception as exc:
            logger.warning("Cannot embed image %s: %s", path.name, exc)
            return f"*Image: {path.name}*"

    def _exif_meta(self, path: Path) -> dict | None:
        """Extract EXIF metadata for front matter. Returns None if not available."""
        if path.suffix.lower() == ".svg":
            return None
        try:
            from PIL import Image, ExifTags  # type: ignore
            img = Image.open(path)
            exif_data = img._getexif()  # type: ignore
            if not exif_data:
                return None
            meta: dict = {}
            for tag_id, value in exif_data.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag in ("DateTime", "Make", "Model", "GPSInfo"):
                    meta[tag.lower()] = str(value)
            return meta if meta else None
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # SVG
    # ──────────────────────────────────────────────────────────────────────────

    def _convert_svg(self, path: Path) -> str:
        if _SVG_TO_MERMAID:
            mermaid = self._svg_to_mermaid(path)
            if mermaid:
                return f"{heading('Diagram', 2)}\n\n```mermaid\n{mermaid}\n```"

        # Fallback 1: extract all text elements
        texts = self._svg_extract_text(path)
        if texts:
            bullets = "\n".join(f"- {t}" for t in texts)
            return f"{heading('SVG Text Content', 2)}\n\n{bullets}"

        # Fallback 2: vision LLM — rasterise SVG and describe it
        logger.debug("SVG has no parseable structure in %s — trying vision LLM", path.name)
        vision_md = self._svg_vision_fallback(path)
        if vision_md:
            return f"## SVG Visual Description\n\n{vision_md}"

        return f"*SVG diagram: {path.name} — no text or parseable structure detected*"

    def _svg_vision_fallback(self, path: Path) -> str:
        """
        Rasterise SVG to PNG via cairosvg or Inkscape, then run vision LLM.
        Returns empty string if neither tool is available.
        """
        import io as _io
        import shutil

        image_bytes: bytes | None = None

        # Try cairosvg (Python library — preferred)
        try:
            import cairosvg  # type: ignore
            image_bytes = cairosvg.svg2png(url=str(path))
        except ImportError:
            pass
        except Exception as exc:
            logger.debug("cairosvg failed on %s: %s", path.name, exc)

        # Try Inkscape CLI fallback
        if image_bytes is None and shutil.which("inkscape"):
            import subprocess, tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                result = subprocess.run(
                    ["inkscape", str(path), "--export-filename", tmp_path],
                    capture_output=True, timeout=30,
                )
                if result.returncode == 0:
                    image_bytes = Path(tmp_path).read_bytes()
            except Exception as exc:
                logger.debug("Inkscape failed on %s: %s", path.name, exc)
            finally:
                import os
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        if not image_bytes:
            logger.debug("Cannot rasterise SVG %s — no cairosvg or Inkscape available", path.name)
            return ""

        try:
            from fullmark.utils.model_client import ModelClient
            client = ModelClient()
            return client.describe_image(image_bytes, mime_type="image/png") or ""
        except Exception as exc:
            logger.debug("Vision LLM for SVG %s failed: %s", path.name, exc)
            return ""

    def _svg_to_mermaid(self, path: Path) -> str:
        """
        Attempt to convert SVG to a Mermaid flowchart.
        Handles simple directed graphs with rect/circle nodes and path/line edges.
        """
        try:
            from lxml import etree  # type: ignore
        except ImportError:
            logger.debug("lxml not installed — cannot parse SVG")
            return ""

        try:
            tree = etree.parse(str(path))
            root = tree.getroot()
        except Exception as exc:
            logger.warning("Cannot parse SVG %s: %s", path.name, exc)
            return ""

        ns = {"svg": "http://www.w3.org/2000/svg"}

        # Collect text labels (potential node names)
        texts = []
        for text_el in root.iter("{http://www.w3.org/2000/svg}text"):
            content = "".join(text_el.itertext()).strip()
            if content:
                texts.append(content)

        if not texts:
            return ""

        # Count shapes to guess diagram type
        rects   = len(list(root.iter("{http://www.w3.org/2000/svg}rect")))
        circles = len(list(root.iter("{http://www.w3.org/2000/svg}circle")))
        paths   = len(list(root.iter("{http://www.w3.org/2000/svg}path")))
        lines   = len(list(root.iter("{http://www.w3.org/2000/svg}line")))

        edges = paths + lines

        # Build a simple flowchart from found text labels
        nodes = [re.sub(r"[^A-Za-z0-9_]", "_", t) for t in texts]
        lines_out = ["flowchart TD"]
        for i, (node, label) in enumerate(zip(nodes, texts)):
            if rects > 0:
                lines_out.append(f"    {node}[\"{label}\"]")
            else:
                lines_out.append(f"    {node}((\"{label}\"))")

        # Link sequential nodes if edges found
        if edges > 0 and len(nodes) > 1:
            for i in range(len(nodes) - 1):
                lines_out.append(f"    {nodes[i]} --> {nodes[i+1]}")

        return "\n".join(lines_out)

    def _svg_extract_text(self, path: Path) -> list[str]:
        try:
            from lxml import etree  # type: ignore
            tree = etree.parse(str(path))
            root = tree.getroot()
            texts = []
            for text_el in root.iter("{http://www.w3.org/2000/svg}text"):
                content = "".join(text_el.itertext()).strip()
                if content:
                    texts.append(content)
            return texts
        except Exception:
            return []
