#!/usr/bin/env python3
"""
fullmark_preflight.py v2.0
--------------------------
System dependency checker for FullMark.
Run before first use to confirm all required tools are installed.

New in v2.0:
  - Auto-discovers ffmpeg and Tesseract in common install locations
  - If found off-PATH, writes FFMPEG_PATH / TESSERACT_CMD to .env automatically
  - Sets them in the current process environment so the rest of the check works

Usage:
    python fullmark_preflight.py

Result: GO / NO-GO for each dependency. System is ready when all
        REQUIRED checks pass (OPTIONAL items may fail without blocking).
"""

import sys
import shutil
import importlib
import os
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Colour helpers (works on Windows 10+ with ANSI support)
# ──────────────────────────────────────────────────────────────────────────────
try:
    import ctypes
    ctypes.windll.kernel32.SetConsoleMode(ctypes.windll.kernel32.GetStdHandle(-11), 7)
except Exception:
    pass  # Non-Windows or already enabled

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def go(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {GREEN}✓ GO{RESET}     {label}{suffix}")


def nogo(label: str, detail: str = "", required: bool = True) -> None:
    tag = f"{RED}✗ NO-GO  {RESET}" if required else f"{YELLOW}~ OPTIONAL{RESET}"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {tag}  {label}{suffix}")


def fixed(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {CYAN}↳ FIXED {RESET}  {label}{suffix}")


# ──────────────────────────────────────────────────────────────────────────────
# Auto-discovery: common install locations per OS
# ──────────────────────────────────────────────────────────────────────────────

_FFMPEG_CANDIDATES: list[Path] = [
    # Windows — common installer paths
    Path(r"C:\FFmpeg\bin\ffmpeg.exe"),
    Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
    Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
    Path(r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"),
    Path(os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe")),
    Path(os.path.expanduser(r"~\scoop\apps\ffmpeg\current\bin\ffmpeg.exe")),
    Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
    Path(r"C:\tools\ffmpeg\bin\ffmpeg.exe"),
    # macOS — Homebrew / MacPorts
    Path("/usr/local/bin/ffmpeg"),
    Path("/opt/homebrew/bin/ffmpeg"),
    Path("/opt/local/bin/ffmpeg"),
    # Linux — standard locations
    Path("/usr/bin/ffmpeg"),
    Path("/usr/local/bin/ffmpeg"),
    Path("/snap/bin/ffmpeg"),
]

_TESSERACT_CANDIDATES: list[Path] = [
    # Windows — standard installer paths
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe")),
    Path(os.path.expanduser(r"~\scoop\apps\tesseract\current\tesseract.exe")),
    Path(r"C:\ProgramData\chocolatey\bin\tesseract.exe"),
    Path(r"C:\tools\Tesseract-OCR\tesseract.exe"),
    # macOS — Homebrew / MacPorts
    Path("/usr/local/bin/tesseract"),
    Path("/opt/homebrew/bin/tesseract"),
    Path("/opt/local/bin/tesseract"),
    # Linux — standard locations
    Path("/usr/bin/tesseract"),
    Path("/usr/local/bin/tesseract"),
    Path("/snap/bin/tesseract"),
]


def _find_in_candidates(candidates: list[Path]) -> Path | None:
    """Return the first existing path from *candidates*, or None."""
    return next((p for p in candidates if p.exists()), None)


def _write_env_key(key: str, value: str) -> bool:
    """
    Write or update *key=value* in .env.
    Creates .env from .env.template if it doesn't exist.
    Returns True if the file was updated.
    """
    env_path = Path(".env")

    # Create .env from template if missing
    if not env_path.exists():
        template = Path(".env.template")
        if template.exists():
            import shutil as sh
            sh.copy(template, env_path)
        else:
            env_path.write_text("", encoding="utf-8")

    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    key_prefix = f"{key}="
    replaced = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        # Replace the key if it exists (even if commented out)
        if stripped.startswith(f"# {key_prefix}") or stripped.startswith(key_prefix):
            new_lines.append(f"{key}={value}\n")
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        # Append at end
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{key}={value}\n")

    env_path.write_text("".join(new_lines), encoding="utf-8")
    return True


def _auto_fix_binary(
    name: str,
    env_key: str,
    candidates: list[Path],
    current_path: str | None,
) -> str | None:
    """
    If *name* is already on PATH, return its path.
    If not, search candidates. If found:
      - set os.environ[env_key] so current session uses it
      - write to .env for future runs
    Returns the resolved path string, or None if not found anywhere.
    """
    # Already on PATH
    if current_path:
        return current_path

    # Check env var override already set
    env_override = os.getenv(env_key, "")
    if env_override and Path(env_override).exists():
        return env_override

    # Search common install locations
    found = _find_in_candidates(candidates)
    if found:
        path_str = str(found)
        os.environ[env_key] = path_str
        _write_env_key(env_key, path_str)
        return path_str

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Check functions
# ──────────────────────────────────────────────────────────────────────────────

def check_python() -> bool:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if ok:
        go("Python", ver)
    else:
        nogo("Python", f"found {ver}, need ≥ 3.11")
    return ok


def check_ffmpeg() -> bool:
    on_path = shutil.which("ffmpeg")
    resolved = _auto_fix_binary("ffmpeg", "FFMPEG_PATH", _FFMPEG_CANDIDATES, on_path)

    if resolved:
        if on_path:
            go("ffmpeg", resolved)
        else:
            fixed("ffmpeg", f"found off-PATH → wrote FFMPEG_PATH to .env  ({resolved})")
        # Make pytesseract / ffmpeg wrappers pick up the path this session
        os.environ.setdefault("FFMPEG_PATH", resolved)
        return True
    else:
        nogo(
            "ffmpeg",
            "not found on PATH or in common install locations — "
            "download from https://ffmpeg.org/download.html",
        )
        return False


def check_tesseract() -> bool:
    on_path = shutil.which("tesseract")
    resolved = _auto_fix_binary(
        "tesseract", "TESSERACT_CMD", _TESSERACT_CANDIDATES, on_path
    )

    if resolved:
        if on_path:
            go("tesseract (pytesseract)", resolved)
        else:
            fixed(
                "tesseract (pytesseract)",
                f"found off-PATH → wrote TESSERACT_CMD to .env  ({resolved})",
            )
        # Tell pytesseract where the binary is right now
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = resolved
        except ImportError:
            pass
        os.environ.setdefault("TESSERACT_CMD", resolved)
        return True
    else:
        nogo(
            "tesseract (pytesseract)",
            "not found on PATH or in common install locations — "
            "download from https://github.com/UB-Mannheim/tesseract/wiki",
        )
        return False


def check_package(pkg: str, import_name: str | None = None, required: bool = True) -> bool:
    import_name = import_name or pkg
    try:
        importlib.import_module(import_name)
        go(pkg)
        return True
    except ImportError as e:
        nogo(pkg, str(e), required=required)
        return False


def check_env() -> bool:
    env_path = Path(".env")
    if env_path.exists():
        go(".env file", str(env_path.resolve()))
        return True
    template = Path(".env.template")
    if template.exists():
        nogo(".env file", "not found — copy .env.template to .env and fill values", required=False)
    else:
        nogo(".env file", "not found — no .env.template either", required=False)
    return False


def check_output_dir() -> bool:
    output_dir = "./output"
    try:
        from dotenv import dotenv_values
        cfg = dotenv_values(".env")
        output_dir = cfg.get("OUTPUT_DIR", "./output")
    except Exception:
        pass

    target = Path(output_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        test_file = target / ".preflight_test"
        test_file.write_text("ok")
        test_file.unlink()
        go("OUTPUT_DIR writable", str(target.resolve()))
        return True
    except Exception as e:
        nogo("OUTPUT_DIR writable", str(e))
        return False


def main() -> None:
    print()
    print(f"{BOLD}FullMark Pre-flight Check  v2.0{RESET}")
    print("─" * 50)
    print(f"  {CYAN}↳ FIXED{RESET}  = found off-PATH, path written to .env automatically")
    print()

    results: list[bool] = []

    # ── System ──────────────────────────────────────────────────────────────
    print(f"{BOLD}System{RESET}")
    results.append(check_python())
    results.append(check_ffmpeg())
    results.append(check_tesseract())

    # ── Core / Config ────────────────────────────────────────────────────────
    print(f"\n{BOLD}Core / Config{RESET}")
    results.append(check_package("python-dotenv", "dotenv"))
    results.append(check_package("click"))
    check_env()
    results.append(check_output_dir())

    # ── Document Agent ───────────────────────────────────────────────────────
    print(f"\n{BOLD}Document Agent{RESET}")
    results.append(check_package("pdfplumber"))
    results.append(check_package("pdfminer.six", "pdfminer"))
    results.append(check_package("python-docx", "docx"))
    results.append(check_package("openpyxl"))
    results.append(check_package("python-pptx", "pptx"))
    results.append(check_package("ebooklib"))
    results.append(check_package("striprtf"))
    results.append(check_package("extract-msg", "extract_msg"))

    # ── Web Agent ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}Web Agent{RESET}")
    results.append(check_package("requests"))
    results.append(check_package("beautifulsoup4", "bs4"))
    results.append(check_package("lxml"))
    results.append(check_package("markdownify"))
    results.append(check_package("youtube-transcript-api", "youtube_transcript_api"))
    results.append(check_package("feedparser"))

    # ── Image Agent ──────────────────────────────────────────────────────────
    print(f"\n{BOLD}Image Agent{RESET}")
    results.append(check_package("Pillow", "PIL"))
    results.append(check_package("pytesseract"))
    check_package("easyocr", required=False)
    check_package("cairosvg", required=False)

    # ── Video Agent ──────────────────────────────────────────────────────────
    print(f"\n{BOLD}Video Agent{RESET}")
    results.append(check_package("openai-whisper", "whisper"))
    results.append(check_package("PySceneDetect", "scenedetect"))
    results.append(check_package("opencv-python", "cv2"))

    # ── Compiler / LLM ───────────────────────────────────────────────────────
    print(f"\n{BOLD}Compiler / LLM{RESET}")
    results.append(check_package("openai"))
    check_package("google-genai", "google.genai", required=False)
    check_package("google-generativeai", "google.generativeai", required=False)
    check_package("anthropic", required=False)
    check_package("ollama", required=False)

    # ── Optional extras ──────────────────────────────────────────────────────
    print(f"\n{BOLD}Optional Document Extras{RESET}")
    check_package("pymupdf", "fitz", required=False)
    check_package("xlrd", required=False)

    # ── Summary ──────────────────────────────────────────────────────────────
    go_count   = sum(1 for r in results if r)
    nogo_count = sum(1 for r in results if not r)
    print()
    print("─" * 50)
    if nogo_count == 0:
        print(f"{GREEN}{BOLD}  SYSTEM: FULL GO — {go_count}/{len(results)} checks passed{RESET}")
        sys.exit(0)
    else:
        print(
            f"{RED}{BOLD}  SYSTEM: {nogo_count} NO-GO item(s) — "
            f"fix before running FullMark{RESET}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()


# ──────────────────────────────────────────────────────────────────────────────
# Colour helpers (works on Windows 10+ with ANSI support)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
