"""
tests/test_file_utils.py
Tests for extract_urls_from_file and is_url_list_file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fullmark.utils.file_utils import extract_urls_from_file, is_url_list_file, url_to_output_name


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


# ──────────────────────────────────────────────────────────────────────────────
# url_to_output_name — URL naming convention
# ──────────────────────────────────────────────────────────────────────────────

class TestUrlToOutputName:
    def test_basic_url_with_path(self):
        name = url_to_output_name("https://example.com/docs/api/auth")
        assert name == "exa_docs_api_auth"

    def test_domain_prefix_three_chars(self):
        name = url_to_output_name("https://python.org")
        assert name.startswith("pyt")

    def test_www_stripped(self):
        name = url_to_output_name("https://www.example.com/page")
        # www. is stripped, prefix comes from "example"
        assert name.startswith("exa")

    def test_html_extension_stripped_from_last_segment(self):
        name = url_to_output_name("https://docs.python.org/3/library/os.html")
        assert not name.endswith(".html")
        assert "os" in name

    def test_root_url_no_path(self):
        name = url_to_output_name("https://example.com")
        assert name == "exa"

    def test_url_with_trailing_slash(self):
        name = url_to_output_name("https://example.com/docs/")
        assert "exa" in name

    def test_result_max_80_chars(self):
        long_url = "https://example.com/" + "/".join(["segment"] * 30)
        name = url_to_output_name(long_url)
        assert len(name) <= 80

    def test_no_double_underscores(self):
        name = url_to_output_name("https://example.com/a/b/c")
        assert "__" not in name

    def test_special_chars_replaced(self):
        name = url_to_output_name("https://example.com/my-page?q=foo")
        # query string should be handled gracefully — no raw ? or = in name
        assert "?" not in name
        assert "=" not in name

