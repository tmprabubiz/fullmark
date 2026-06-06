"""
tests/test_document_agent.py
Tests for DocumentAgent — mocks all I/O.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fullmark import AgentError
from fullmark.agents.document_agent import DocumentAgent


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _agent() -> DocumentAgent:
    return DocumentAgent()


def _make_temp_file(suffix: str, content: bytes = b"") -> Path:
    """Write *content* to a temp file with *suffix* and return its Path."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


# ──────────────────────────────────────────────────────────────────────────────
# TXT
# ──────────────────────────────────────────────────────────────────────────────

class TestTxt:
    def test_convert_txt_returns_string(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("Hello World\n\nSecond paragraph.", encoding="utf-8")
        result = _agent().convert(f)
        assert isinstance(result, str)

    def test_convert_txt_contains_front_matter(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Some notes.", encoding="utf-8")
        result = _agent().convert(f)
        assert "---" in result
        assert "agent: DocumentAgent" in result

    def test_convert_txt_preserves_content(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("Important content here.", encoding="utf-8")
        result = _agent().convert(f)
        assert "Important content here." in result


# ──────────────────────────────────────────────────────────────────────────────
# CSV
# ──────────────────────────────────────────────────────────────────────────────

class TestCsv:
    def test_convert_csv_returns_gfm_table(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("Name,Age,City\nAlice,30,NYC\nBob,25,LA", encoding="utf-8")
        result = _agent().convert(f)
        assert "| Name |" in result
        assert "| Alice |" in result

    def test_convert_csv_has_front_matter(self, tmp_path):
        f = tmp_path / "table.csv"
        f.write_text("A,B\n1,2", encoding="utf-8")
        result = _agent().convert(f)
        assert "source: table.csv" in result

    def test_convert_empty_csv(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        result = _agent().convert(f)
        assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────────────────────
# IPYNB
# ──────────────────────────────────────────────────────────────────────────────

class TestIpynb:
    def _make_notebook(self, tmp_path: Path) -> Path:
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"language": "python"}},
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["# Title\n", "Some intro."],
                    "metadata": {},
                },
                {
                    "cell_type": "code",
                    "source": ["print('hello')"],
                    "outputs": [
                        {"output_type": "stream", "text": ["hello\n"]}
                    ],
                    "metadata": {},
                },
            ],
        }
        f = tmp_path / "notebook.ipynb"
        f.write_text(json.dumps(nb), encoding="utf-8")
        return f

    def test_convert_ipynb_returns_string(self, tmp_path):
        f = self._make_notebook(tmp_path)
        result = _agent().convert(f)
        assert isinstance(result, str)

    def test_convert_ipynb_has_front_matter(self, tmp_path):
        f = self._make_notebook(tmp_path)
        result = _agent().convert(f)
        assert "agent: DocumentAgent" in result

    def test_convert_ipynb_preserves_markdown_cells(self, tmp_path):
        f = self._make_notebook(tmp_path)
        result = _agent().convert(f)
        assert "# Title" in result

    def test_convert_ipynb_fences_code_cells(self, tmp_path):
        f = self._make_notebook(tmp_path)
        result = _agent().convert(f)
        assert "```python" in result


# ──────────────────────────────────────────────────────────────────────────────
# Error paths
# ──────────────────────────────────────────────────────────────────────────────

class TestErrors:
    def test_convert_nonexistent_file_raises(self):
        with pytest.raises(AgentError, match="not found"):
            _agent().convert("/nonexistent/file.pdf")

    def test_convert_unsupported_extension_raises(self, tmp_path):
        f = tmp_path / "file.xyz"
        f.write_text("data")
        with pytest.raises(AgentError, match="unsupported"):
            _agent().convert(f)

    def test_convert_pdf_pdfplumber_import_error(self, tmp_path):
        """Falls back gracefully when pdfplumber is missing."""
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        agent = _agent()
        with patch.object(agent, "_pdf_pdfplumber", return_value=""), \
             patch.object(agent, "_pdf_pdfminer", return_value="Sample text"), \
             patch.object(agent, "_pdf_ocr", return_value=""):
            result = agent.convert(f)
        assert "Sample text" in result


# ──────────────────────────────────────────────────────────────────────────────
# DOCX (mocked)
# ──────────────────────────────────────────────────────────────────────────────

class TestDocx:
    def test_convert_docx_mocked(self, tmp_path):
        """Mock python-docx to test DOCX conversion logic."""
        f = tmp_path / "report.docx"
        f.write_bytes(b"fake docx content")

        para1 = MagicMock()
        para1.style.name = "Heading 1"
        para1.text = "Introduction"

        para2 = MagicMock()
        para2.style.name = "Normal"
        para2.text = "Body text here."

        mock_doc = MagicMock()
        mock_doc.paragraphs = [para1, para2]
        mock_doc.tables = []

        with patch("docx.Document", return_value=mock_doc):
            result = _agent().convert(f)

        assert "# Introduction" in result
        assert "Body text here." in result
        assert "agent: DocumentAgent" in result
