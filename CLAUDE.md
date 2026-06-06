# CLAUDE.md — FullMark Master Brain File

> This file is read FIRST by any coding agent working on FullMark.
> All architecture, tool choices, agent specs, fallback rules, and coding standards are here.

---

## 1. Project Identity

- **Tool Name:** FullMark
- **Purpose:** Convert ANY source format into a perfect Markdown file
- **Tagline:** *Full Marks — Every source, Perfect Markdown*
- **License:** MIT
- **Repo:** `tmprabubiz/fullmark`

---

## 2. Architecture — Agent Design

```
ORCHESTRATOR AGENT (extension + MIME routing)
        │
        ├── DOCUMENT AGENT   → PDF, DOCX, PPTX, XLSX, EPUB, CSV, RTF, TXT, ODS, ODP
        ├── WEB AGENT        → URL, HTML, RSS, YouTube URL
        ├── IMAGE AGENT      → JPG, PNG, BMP, TIFF, WebP, SVG
        └── VIDEO AGENT      → MP4, AVI, MOV, MKV, WEBM, MP3, WAV, M4A
                │
                └── COMPILER AGENT (merges audio + vision → Markdown)
```

### File Layout

```
fullmark/
  __init__.py
  orchestrator.py
  agents/
    __init__.py
    document_agent.py
    web_agent.py
    image_agent.py
    video_agent.py
    compiler_agent.py
  utils/
    __init__.py
    model_client.py      ← LLM provider fallback chain
    markdown_utils.py    ← shared Markdown helpers
    file_utils.py        ← extension/MIME detection, ZIP unpacking
tests/
  __init__.py
  test_document_agent.py
  test_web_agent.py
  test_image_agent.py
  test_video_agent.py
  test_orchestrator.py
  fixtures/
fullmark_cli.py          ← CLI entry point (`python fullmark_cli.py <input>`)
fullmark_preflight.py    ← system dependency checker
requirements.txt
.env.template
```

---

## 3. Orchestrator Rules

- Detect input type by **extension** first, **MIME** as fallback
- Route to exactly ONE agent — no overlap
- Handle ZIP: unpack → route each file individually → combine outputs
- Handle directory input: walk all files → route each → combine outputs
- Log every routing decision to stderr
- If an agent raises an exception → log error → continue with remaining files
- Return a list of `(source_path, markdown_string)` tuples
- Final output file: `<original_name>.md` in `OUTPUT_DIR`

### Routing Table

| Extension(s) | Agent |
|---|---|
| `.pdf`, `.docx`, `.doc`, `.rtf`, `.txt`, `.epub`, `.xlsx`, `.xls`, `.csv`, `.ods`, `.pptx`, `.ppt`, `.odp` | Document Agent |
| `.html`, `.htm` or starts with `http://` / `https://` | Web Agent |
| `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.svg` | Image Agent |
| `.mp4`, `.avi`, `.mov`, `.mkv`, `.webm`, `.mp3`, `.wav`, `.m4a` | Video Agent |
| `.zip` | Orchestrator (unpack → re-route each file) |
| `.ipynb` | Document Agent (notebook reader) |
| `.msg`, `.eml` | Document Agent (email reader) |

---

## 4. Tool Choices Per Agent

### Document Agent (`agents/document_agent.py`)
| Task | Tool |
|---|---|
| PDF text + tables | `pdfplumber` primary, `pdfminer.six` fallback |
| Scanned PDF (image-based) | `pytesseract` fallback |
| Word documents | `python-docx` |
| Spreadsheets XLSX/ODS | `openpyxl` |
| CSV | stdlib `csv` |
| Presentations PPTX/ODP | `python-pptx` |
| EPUB | `ebooklib` + `BeautifulSoup4` |
| Notebooks IPYNB | stdlib `json` |
| Email MSG | `extract-msg` |
| Email EML | stdlib `email` |
| RTF | `striprtf` |

### Web Agent (`agents/web_agent.py`)
| Task | Tool |
|---|---|
| HTML parsing | `beautifulsoup4` + `lxml` |
| URL fetching | `requests` |
| HTML → Markdown | `markdownify` |
| Auto image download | `requests` → sequential `image-001.jpg` naming |
| YouTube transcript | `youtube-transcript-api` |
| RSS feeds | `feedparser` |

### Image Agent (`agents/image_agent.py`)
| Task | Tool |
|---|---|
| OCR primary | `pytesseract` |
| OCR fallback | `easyocr` |
| Table image → Markdown table | `pytesseract` + layout logic |
| SVG → Mermaid | `lxml` + custom parser |
| Decorative images | `Pillow` → base64 embed |
| Image metadata | `Pillow` EXIF |

### Video Agent (`agents/video_agent.py`)
| Task | Tool |
|---|---|
| Video handling | `ffmpeg` (system binary via `subprocess`) |
| Scene change detection | `PySceneDetect` + `opencv-python` |
| Frame extraction on change | `opencv-python` → high-res JPEG + timestamp |
| Audio extraction | `ffmpeg` |
| Audio transcription + timestamps | `openai-whisper` (local, free) |
| OCR on extracted frames | Image Agent (reused) |

### Compiler Agent (`agents/compiler_agent.py`)
| Task | Tool |
|---|---|
| Merge audio transcript + visual OCR | LLM via `utils/model_client.py` |
| Chronological alignment | Timestamp matching logic |
| Output formatting | Headers, bullet points, Markdown tables |

---

## 5. Compiler Model Config — Priority Chain

See `.env.template` for full config.

```
PRIMARY    → Gemini free tier (GEMINI_API_KEY)
FALLBACK_1 → Any OpenAI-compatible provider (OPENAI_API_KEY + OPENAI_BASE_URL)
FALLBACK_2 → Ollama local (OLLAMA_BASE_URL — no key needed)
FALLBACK_3 → None (output raw uncompiled text with warning)
```

The `utils/model_client.py` module implements this chain.
Call `model_client.complete(prompt)` — it handles all fallback internally.

---

## 6. Output Specification

- Output directory: `OUTPUT_DIR` from `.env` (default `./output`)
- File naming: `<original_stem>.md`
- Images embedded as base64 in `![alt](data:image/jpeg;base64,...)` for decorative
- Data images (charts, screenshots) saved as `image-001.jpg` alongside `.md`
- SVG diagrams converted to Mermaid code blocks
- Tables extracted as GFM pipe tables
- Headings preserved from source structure
- Code blocks fenced with language tag when detectable
- Front matter added:

```yaml
---
source: <original filename>
converted: <ISO8601 timestamp>
agent: <agent name>
---
```

---

## 7. Coding Standards

- Python 3.11+
- Type hints on all public functions
- Docstrings on all public classes and functions (one-line summary + Args + Returns)
- All agents are classes with a `convert(source: str | Path) -> str` method
- Agents raise `AgentError` (defined in `fullmark/__init__.py`) on unrecoverable failure
- Graceful degradation: catch import errors → log warning → skip optional feature
- No hard dependencies on paid APIs — always a free fallback path
- No `print()` in library code — use `logging.getLogger(__name__)`
- Tests use `pytest`, mocking external calls with `unittest.mock`

---

## 8. What NOT To Do

- Do NOT force any paid API — every feature must have a free path
- Do NOT use Azure/Microsoft Cognitive services
- Do NOT store API keys in code — only via `.env`
- Do NOT call `.env` without `python-dotenv` load
- Do NOT skip the fallback chain in `model_client.py`
- Do NOT print to stdout from library code (use logging)
- Do NOT create output files outside `OUTPUT_DIR`

---

## 9. Test Requirements

Each agent must have:
- At least 3 unit tests
- Tests mock all I/O (file reads, HTTP calls, subprocess)
- Test happy path + at least one error path
- Test that output contains Markdown front matter
- Test that `convert()` returns a string

---
*CLAUDE.md generated from HANDOFF.md — Session 2*
