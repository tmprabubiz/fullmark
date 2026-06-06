"""
tests/test_file_utils.py
Tests for extract_urls_from_file and is_url_list_file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fullmark.utils.file_utils import extract_urls_from_file, is_url_list_file


class TestExtractUrlsFromTxt:
    def test_valid_urls_extracted(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("https://example.com\nhttps://test.org\n", encoding="utf-8")
        urls, skipped = extract_urls_from_file(f)
        assert urls == ["https://example.com", "https://test.org"]
        assert skipped == []

    def test_non_url_lines_go_to_skipped(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("https://example.com\nnot a url\njust text\n", encoding="utf-8")
        urls, skipped = extract_urls_from_file(f)
        assert "https://example.com" in urls
        assert "not a url" in skipped
        assert "just text" in skipped

    def test_empty_lines_ignored(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("\n\nhttps://example.com\n\n", encoding="utf-8")
        urls, skipped = extract_urls_from_file(f)
        assert urls == ["https://example.com"]
        assert skipped == []

    def test_http_and_https_both_accepted(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("http://example.com\nhttps://secure.org\n", encoding="utf-8")
        urls, _ = extract_urls_from_file(f)
        assert len(urls) == 2

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        urls, skipped = extract_urls_from_file(f)
        assert urls == []
        assert skipped == []


class TestExtractUrlsFromCsv:
    def test_csv_urls_extracted(self, tmp_path):
        f = tmp_path / "links.csv"
        f.write_text("https://example.com,label\nhttps://test.org,other\n", encoding="utf-8")
        urls, skipped = extract_urls_from_file(f)
        assert "https://example.com" in urls
        assert "https://test.org" in urls
        # "label" and "other" go to skipped
        assert "label" in skipped


class TestIsUrlListFile:
    def test_txt_with_urls_is_url_list(self, tmp_path):
        f = tmp_path / "links.txt"
        f.write_text("https://example.com\n", encoding="utf-8")
        assert is_url_list_file(f) is True

    def test_txt_without_urls_is_not_url_list(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Just some notes\nNo URLs here\n", encoding="utf-8")
        assert is_url_list_file(f) is False

    def test_jpg_is_never_url_list(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake")
        assert is_url_list_file(f) is False

    def test_pdf_is_never_url_list(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4")
        assert is_url_list_file(f) is False
