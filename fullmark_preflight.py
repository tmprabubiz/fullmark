#!/usr/bin/env python3
"""
fullmark_preflight.py v1.1
--------------------------
System dependency checker for FullMark.
Run before first use to confirm all required tools are installed.

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
RESET  = "\033[0m"
BOLD   = "\033[1m"


def go(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {GREEN}✓ GO{RESET}     {label}{suffix}")


def nogo(label: str, detail: str = "", required: bool = True) -> None:
    tag = f"{RED}✗ NO-GO  {RESET}" if required else f"{YELLOW}~ OPTIONAL{RESET}"
    suffix = f"  ({detail})" if detail else ""
    print(f"  {tag}  {label}{suffix}")


def check_python() -> bool:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if ok:
        go("Python", ver)
    else:
        nogo("Python", f"found {ver}, need ≥ 3.11")
    return ok


def check_binary(name: str, label: str, required: bool = True) -> bool:
    path = shutil.which(name)
    ok = path is not None
    if ok:
        go(label, path)
    else:
        nogo(label, f"'{name}' not found on PATH", required=required)
    return ok


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
    # Try to load OUTPUT_DIR from .env if available
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
        # Write a temp file to confirm writable
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
    print(f"{BOLD}FullMark Pre-flight Check{RESET}")
    print("─" * 50)

    results: list[bool] = []

    # ── System ──────────────────────────────────────────────────────────────
    print(f"\n{BOLD}System{RESET}")
    results.append(check_python())
    results.append(check_binary("ffmpeg", "ffmpeg"))
    results.append(check_binary("tesseract", "tesseract (pytesseract)"))

    # ── Core / Config ────────────────────────────────────────────────────────
    print(f"\n{BOLD}Core / Config{RESET}")
    results.append(check_package("python-dotenv", "dotenv"))
    results.append(check_package("click"))
    check_env()         # informational — not blocking
    results.append(check_output_dir())

    # ── Document Agent packages ──────────────────────────────────────────────
    print(f"\n{BOLD}Document Agent{RESET}")
    results.append(check_package("pdfplumber"))
    results.append(check_package("pdfminer.six", "pdfminer"))
    results.append(check_package("python-docx", "docx"))
    results.append(check_package("openpyxl"))
    results.append(check_package("python-pptx", "pptx"))
    results.append(check_package("ebooklib"))
    results.append(check_package("striprtf"))
    results.append(check_package("extract-msg", "extract_msg"))

    # ── Web Agent packages ───────────────────────────────────────────────────
    print(f"\n{BOLD}Web Agent{RESET}")
    results.append(check_package("requests"))
    results.append(check_package("beautifulsoup4", "bs4"))
    results.append(check_package("lxml"))
    results.append(check_package("markdownify"))
    results.append(check_package("youtube-transcript-api", "youtube_transcript_api"))
    results.append(check_package("feedparser"))

    # ── Image Agent packages ─────────────────────────────────────────────────
    print(f"\n{BOLD}Image Agent{RESET}")
    results.append(check_package("Pillow", "PIL"))
    results.append(check_package("pytesseract"))
    check_package("easyocr", required=False)  # optional fallback

    # ── Video Agent packages ─────────────────────────────────────────────────
    print(f"\n{BOLD}Video Agent{RESET}")
    results.append(check_package("openai-whisper", "whisper"))
    results.append(check_package("PySceneDetect", "scenedetect"))
    results.append(check_package("opencv-python", "cv2"))

    # ── Compiler / LLM packages ──────────────────────────────────────────────
    print(f"\n{BOLD}Compiler / LLM{RESET}")
    results.append(check_package("openai"))
    check_package("google-generativeai", "google.generativeai", required=False)
    check_package("ollama", required=False)

    # ── Summary ──────────────────────────────────────────────────────────────
    go_count  = sum(1 for r in results if r)
    nogo_count = sum(1 for r in results if not r)
    print()
    print("─" * 50)
    if nogo_count == 0:
        print(f"{GREEN}{BOLD}  SYSTEM: FULL GO — {go_count}/{len(results)} checks passed{RESET}")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}  SYSTEM: {nogo_count} NO-GO items found — fix before running FullMark{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
