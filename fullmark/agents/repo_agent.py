"""
fullmark/agents/repo_agent.py
------------------------------
Converts a GitHub repository to a structured Markdown document.

Uses the GitHub Trees API (a single authenticated request) to list all files,
then fetches each text file via raw.githubusercontent.com — no git clone needed.

GITHUB TERMS OF SERVICE
-----------------------
This agent uses the **GitHub REST API** (api.github.com) and
**raw.githubusercontent.com** CDN — both are public, documented interfaces
intended for programmatic access. This is explicitly within GitHub's
Acceptable Use Policy:
  https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies

Rate limits:
  - Unauthenticated : 60 API requests / hour (raw CDN not counted)
  - Authenticated   : 5,000 API requests / hour (add GITHUB_TOKEN to .env)

Set GITHUB_TOKEN in .env for a free token with higher limits:
  https://github.com/settings/tokens  (no scopes needed for public repos)

WHAT IS FETCHED
---------------
- All text-based files (code, config, docs, data)
- Files are grouped by directory in the output
- Binary files, files > REPO_MAX_FILE_KB, and common noise paths are skipped

WHAT IS SKIPPED
---------------
Common skip patterns (configurable via REPO_SKIP_PATTERNS in .env):
  node_modules/, .git/, __pycache__/, .venv/, dist/, build/,
  *.min.js, *.map, lock files, compiled objects

USAGE
-----
    fullmark_cli.py https://github.com/owner/repo
    fullmark_cli.py https://github.com/owner/repo/tree/main/src
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fullmark import AgentError
from fullmark.utils.file_utils import LANG_MAP
from fullmark.utils.markdown_utils import front_matter

logger = logging.getLogger(__name__)

_AGENT_NAME = "RepoAgent"

# GitHub API base
_API_BASE = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"

# Default file size limit (KB) — files larger than this are noted but not embedded
_DEFAULT_MAX_FILE_KB = int(os.getenv("REPO_MAX_FILE_KB", "200"))

# Delay between raw file fetches (seconds) — be a polite client
_FETCH_DELAY = float(os.getenv("REPO_FETCH_DELAY", "0.2"))

# Default skip patterns (regex, applied to the full path inside the repo)
_DEFAULT_SKIP_PATTERNS: list[str] = [
    r"^\.git/",
    r"/node_modules/",
    r"/__pycache__/",
    r"/\.venv/",
    r"/venv/",
    r"/dist/",
    r"/build/",
    r"/\.next/",
    r"/\.nuxt/",
    r"\.min\.js$",
    r"\.min\.css$",
    r"\.map$",
    r"\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"poetry\.lock$",
    r"uv\.lock$",
    r"\.pyc$",
    r"\.pyo$",
    r"\.class$",
    r"\.o$",
    r"\.obj$",
    r"\.exe$",
    r"\.dll$",
    r"\.so$",
    r"\.dylib$",
]

# Binary file extensions — fetched as metadata only, not embedded
_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".tiff", ".webp",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".mp4", ".mp3", ".wav", ".avi", ".mov",
    ".ttf", ".woff", ".woff2", ".eot", ".otf",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat",
})


class RepoAgent:
    """
    Convert a public GitHub repository to a structured Markdown document.

    Parses ``https://github.com/{owner}/{repo}[/tree/{branch}[/{subpath}]]``
    and produces a single Markdown file documenting the entire repo tree.
    """

    def convert(self, source: str | Path) -> str:
        """
        Fetch and convert a GitHub repository.

        Args:
            source: GitHub repository URL.

        Returns:
            Markdown string with YAML front matter.

        Raises:
            AgentError: If the repo cannot be accessed or the URL is invalid.
        """
        url = str(source)
        owner, repo, branch, subpath = self._parse_url(url)
        logger.info("RepoAgent: %s/%s  branch=%s  path=%s", owner, repo, branch or "default", subpath or "/")

        session = self._make_session()
        resolved_branch = branch or self._get_default_branch(session, owner, repo)

        # Fetch the complete file tree in one API call
        tree = self._get_tree(session, owner, repo, resolved_branch)

        # Filter to relevant files
        files = self._filter_tree(tree, subpath)
        total = len(files)
        logger.info("RepoAgent: %d files to process (after filtering)", total)

        if total == 0:
            raise AgentError(f"No processable files found in {url}")

        # Warn if repo is large
        if total > 200:
            logger.warning(
                "RepoAgent: large repo (%d files). Consider using a subpath to narrow scope. "
                "e.g. https://github.com/%s/%s/tree/%s/src",
                total, owner, repo, resolved_branch,
            )

        # Fetch file contents and build output
        sections = self._fetch_all(session, owner, repo, resolved_branch, files)

        body = self._build_markdown(owner, repo, resolved_branch, subpath, files, sections)
        fm = front_matter(f"github.com/{owner}/{repo}", _AGENT_NAME)
        return f"{fm}\n\n{body}"

    # ──────────────────────────────────────────────────────────────────────────
    # URL parsing
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_url(url: str) -> tuple[str, str, str | None, str | None]:
        """
        Parse a GitHub URL into (owner, repo, branch, subpath).

        Handles:
          https://github.com/owner/repo
          https://github.com/owner/repo/tree/main
          https://github.com/owner/repo/tree/main/src/utils
        """
        pattern = re.compile(
            r"https://github\.com/([^/]+)/([^/]+)"
            r"(?:/tree/([^/]+)(?:/(.+))?)?",
            re.IGNORECASE,
        )
        m = pattern.match(url.rstrip("/"))
        if not m:
            raise AgentError(f"Cannot parse GitHub URL: {url}")
        owner, repo, branch, subpath = m.group(1), m.group(2), m.group(3), m.group(4)
        return owner, repo, branch, subpath

    # ──────────────────────────────────────────────────────────────────────────
    # GitHub API helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _make_session(self):
        """Create a requests.Session with optional auth and user-agent."""
        try:
            import requests
        except ImportError:
            raise AgentError("requests is required for RepoAgent — pip install requests")

        session = requests.Session()
        token = os.getenv("GITHUB_TOKEN", "")
        if token:
            session.headers["Authorization"] = f"Bearer {token}"
            logger.debug("RepoAgent: using GITHUB_TOKEN (authenticated, 5000 req/hr)")
        else:
            logger.info(
                "RepoAgent: no GITHUB_TOKEN — using unauthenticated API (60 req/hr). "
                "Set GITHUB_TOKEN in .env for higher limits."
            )
        session.headers["Accept"] = "application/vnd.github.v3+json"
        session.headers["User-Agent"] = "FullMark/1.0 (+https://github.com/tmprabubiz/fullmark)"
        return session

    def _get_default_branch(self, session, owner: str, repo: str) -> str:
        """Query the repo metadata for its default branch."""
        resp = session.get(f"{_API_BASE}/repos/{owner}/{repo}", timeout=30)
        if resp.status_code == 404:
            raise AgentError(f"Repository not found: github.com/{owner}/{repo} (may be private or misspelled)")
        if resp.status_code == 403:
            raise AgentError(
                f"GitHub API rate limit exceeded for github.com/{owner}/{repo}. "
                "Add GITHUB_TOKEN to .env for higher limits."
            )
        resp.raise_for_status()
        data = resp.json()
        branch = data.get("default_branch", "main")
        logger.debug("RepoAgent: default branch = %s", branch)
        return branch

    def _get_tree(self, session, owner: str, repo: str, branch: str) -> list[dict]:
        """
        Fetch the complete recursive file tree via the Git Trees API.

        Returns a list of tree entry dicts with keys: path, type, size, sha, url.
        """
        api_url = f"{_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        resp = session.get(api_url, timeout=60)
        if resp.status_code == 409:
            raise AgentError(f"Repository {owner}/{repo} appears to be empty.")
        if resp.status_code == 403:
            raise AgentError(
                "GitHub API rate limit exceeded. Add GITHUB_TOKEN to .env or wait and retry."
            )
        resp.raise_for_status()
        data = resp.json()

        if data.get("truncated"):
            logger.warning(
                "RepoAgent: tree was truncated by GitHub (>100k entries). "
                "Use a subpath to narrow scope."
            )

        return [e for e in data.get("tree", []) if e.get("type") == "blob"]

    # ──────────────────────────────────────────────────────────────────────────
    # File filtering
    # ──────────────────────────────────────────────────────────────────────────

    def _filter_tree(self, tree: list[dict], subpath: str | None) -> list[dict]:
        """
        Filter tree entries to those we want to fetch.

        Applies:
        - subpath prefix filter (if given)
        - skip patterns
        - binary extension exclusion (kept as stubs)
        - size limit (> REPO_MAX_FILE_KB skipped)
        """
        extra_patterns = os.getenv("REPO_SKIP_PATTERNS", "").split(",")
        skip_re = [
            re.compile(p.strip(), re.IGNORECASE)
            for p in _DEFAULT_SKIP_PATTERNS + [p for p in extra_patterns if p.strip()]
        ]

        max_bytes = _DEFAULT_MAX_FILE_KB * 1024
        result: list[dict] = []

        for entry in tree:
            path = entry.get("path", "")

            # Subpath filter
            if subpath and not path.startswith(subpath.strip("/")):
                continue

            # Skip patterns
            search_path = "/" + path  # prefix slash for pattern matching
            if any(r.search(search_path) for r in skip_re):
                continue

            # Size filter
            size = entry.get("size", 0) or 0
            if size > max_bytes:
                logger.debug("Skipping large file (%d KB): %s", size // 1024, path)
                continue

            result.append(entry)

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # File fetching
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_all(
        self,
        session,
        owner: str,
        repo: str,
        branch: str,
        files: list[dict],
    ) -> dict[str, str | None]:
        """
        Fetch raw content for each file.

        Returns a dict mapping ``path → text_content`` (None for binary/failed).
        Uses raw.githubusercontent.com which is not subject to API rate limits.
        """
        results: dict[str, str | None] = {}
        total = len(files)

        for i, entry in enumerate(files, start=1):
            path = entry["path"]
            ext = PurePosixPath(path).suffix.lower()

            if ext in _BINARY_EXTENSIONS:
                logger.debug("[%d/%d] skipping binary: %s", i, total, path)
                results[path] = None
                continue

            raw_url = f"{_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
            logger.debug("[%d/%d] fetching: %s", i, total, path)

            try:
                resp = session.get(raw_url, timeout=30)
                resp.raise_for_status()
                # Try to decode; skip silently if binary
                try:
                    results[path] = resp.content.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        results[path] = resp.content.decode("latin-1")
                    except UnicodeDecodeError:
                        logger.debug("Cannot decode %s as text — treating as binary", path)
                        results[path] = None
            except Exception as exc:
                logger.warning("Failed to fetch %s: %s", path, exc)
                results[path] = None

            # Polite delay between raw fetches
            if i < total and _FETCH_DELAY > 0:
                time.sleep(_FETCH_DELAY)

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Markdown assembly
    # ──────────────────────────────────────────────────────────────────────────

    def _build_markdown(
        self,
        owner: str,
        repo: str,
        branch: str,
        subpath: str | None,
        files: list[dict],
        contents: dict[str, str | None],
    ) -> str:
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        scope = f"`{subpath}/`" if subpath else "entire repository"
        total = len(files)
        fetched = sum(1 for v in contents.values() if v is not None)
        skipped = total - fetched

        lines: list[str] = [
            f"# {owner}/{repo}",
            "",
            f"> Converted by FullMark · branch `{branch}` · {now}  ",
            f"> Scope: {scope} · {fetched} files embedded · {skipped} binary/skipped",
            "",
            "---",
            "",
            "## Repository Structure",
            "",
            "```",
        ]

        # Print directory tree
        for entry in files:
            depth = entry["path"].count("/")
            indent = "  " * depth
            name = PurePosixPath(entry["path"]).name
            size_kb = (entry.get("size") or 0) / 1024
            marker = "📄" if contents.get(entry["path"]) is not None else "⊘ "
            lines.append(f"{indent}{marker} {name}  ({size_kb:.1f} KB)")

        lines += ["```", "", "---", ""]

        # Group files by directory
        dirs: dict[str, list[dict]] = {}
        for entry in files:
            d = str(PurePosixPath(entry["path"]).parent)
            dirs.setdefault(d, []).append(entry)

        for dir_path in sorted(dirs):
            display_dir = dir_path if dir_path != "." else f"{repo}/"
            lines += [f"## 📁 {display_dir}", ""]

            for entry in dirs[dir_path]:
                file_path = entry["path"]
                filename = PurePosixPath(file_path).name
                ext = PurePosixPath(file_path).suffix.lower()
                lang = LANG_MAP.get(ext, "")
                content = contents.get(file_path)

                lines.append(f"### `{filename}`")
                lines.append("")

                if content is None:
                    size_kb = (entry.get("size") or 0) / 1024
                    lines.append(f"*Binary file or skipped ({size_kb:.1f} KB)*")
                else:
                    # Escape triple backticks inside file content
                    safe_content = content.replace("```", "` ` `")
                    lines.append(f"```{lang}")
                    lines.append(safe_content.rstrip())
                    lines.append("```")

                lines.append("")

        return "\n".join(lines)
