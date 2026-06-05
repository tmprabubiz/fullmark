# FullMark — Project Handoff Document
> This file captures every decision made in the planning session.
> Paste this into any fresh Copilot/Claude session to continue without re-reading history.
> DO NOT delete. DO NOT publish sensitive keys here.

---

## 1. Project Identity

| Item | Value |
|---|---|
| Tool Name | **FullMark** |
| Repo | `tmprabubiz/fullmark` |
| Owner | tmprabubiz |
| License | MIT |
| Visibility | Public |
| Purpose | Convert ANY source format into a perfect Markdown file |
| Tagline | *Full Marks — Every source, Perfect Markdown* |
| VS Code Extension | Planned as Phase 2 after core engine |

---

## 2. What FullMark Does

Converts ALL of the following into structured, clean Markdown files:

### Input Formats Supported
| Category | Formats |
|---|---|
| Documents | PDF, DOCX, RTF, TXT, EPUB |
| Spreadsheets | XLSX, CSV, ODS |
| Slideshows | PPTX, ODP |
| Images | JPG, PNG, BMP, TIFF, WebP, SVG |
| Video | MP4, AVI, MOV, MKV, WEBM |
| Audio | MP3, WAV, M4A (transcript only) |
| Web | URL, HTML, RSS Feed, YouTube URL |
| Archives | ZIP (containing any of the above) |
| Notebooks | IPYNB |
| Email | Outlook MSG, EML |

---

## 3. Architecture — Agent Design

```
ORCHESTRATOR AGENT (RLM routing)
        │
        ├── DOCUMENT AGENT   → PDF, DOCX, PPTX, XLSX, EPUB, CSV
        ├── WEB AGENT        → URL, HTML, RSS, YouTube
        ├── IMAGE AGENT      → JPG, PNG, SVG, OCR, base64
        └── VIDEO AGENT      → MP4, scene detect, Whisper, OCR frames
                │
                └── COMPILER AGENT (merges audio + vision → Markdown)
```

### Orchestrator Rules
- Detects input type by extension + MIME
- Routes to correct agent — no overlap
- Handles ZIP by unpacking and routing each file
- Logs every routing decision
- Self-fallback: if agent fails → log error → continue with next file

---

## 4. Tool Choices Per Agent (ALL FREE)

### Document Agent
| Task | Tool |
|---|---|
| PDF text + tables | `pdfplumber` primary, `pdfminer.six` fallback |
| Scanned PDF (image-based) | `pytesseract` fallback |
| Word documents | `python-docx` |
| Spreadsheets | `openpyxl` |
| Presentations | `python-pptx` |
| EPUB | `ebooklib` |

### Web Agent
| Task | Tool |
|---|---|
| HTML parsing | `beautifulsoup4` + `lxml` |
| URL fetching | `requests` |
| HTML → Markdown | `markdownify` |
| Auto image download | `requests` + sequential naming `image-001.jpg` |
| YouTube transcript | `youtube-transcript-api` |
| RSS feeds | `feedparser` |

### Image Agent
| Task | Tool |
|---|---|
| OCR (text, tables in images) | `pytesseract` primary, `easyocr` fallback |
| Table image → Markdown table | `pytesseract` + layout logic |
| SVG → Mermaid | `lxml` + custom parser |
| Decorative images (faces, metaphors) | `Pillow` → base64 embed in .md |
| Image metadata | `Pillow` EXIF |

### Video Agent
| Task | Tool |
|---|---|
| Video handling | `ffmpeg` (system binary) |
| Scene change detection | `PySceneDetect` + `opencv-python` |
| Frame extraction on change | `opencv-python` → high-res JPEG + timestamp |
| Audio extraction | `ffmpeg` |
| Audio transcription + timestamps | `openai-whisper` (local, free) |
| OCR on extracted frames | Image Agent (reused) |

### Compiler Agent
| Task | Tool |
|---|---|
| Merge audio transcript + visual OCR | LLM via .env config |
| Chronological alignment | Timestamp matching logic |
| Output formatting | Headers, bullet points, Markdown tables |

---

## 5. Compiler Model Config — Priority Chain

User sets in `.env`:
```
PRIMARY    → Gemini free tier (direct)
FALLBACK_1 → OpenRouter (covers Groq, Mistral, Llama, Claude, 100+ models)
FALLBACK_2 → Ollama local (Mistral, Llama3 — fully offline)
FALLBACK_3 → None (output uncompiled, warn user)
```

### OpenAI-Compatible Universal Design
Any OpenAI-SDK-compatible provider works by setting:
- `OPENAI_BASE_URL` = provider endpoint
- `OPENAI_API_KEY` = provider key
- `OPENAI_MODEL` = model name

Covers: OpenRouter, Nvidia NIM, Groq, Together AI, LM Studio, Fireworks, Anyscale.

---

## 6. .env.template Structure

```
# FullMark Compiler Model Configuration
# Copy this file to .env and fill your values
# NEVER commit .env to GitHub

# Option A: Any OpenAI-compatible provider (OpenRouter recommended)
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=google/gemini-2.0-flash-exp:free

# Option B: Google Gemini Direct
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-2.0-flash

# Option C: Ollama Local (no key needed)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=mistral

# Fallback Priority
COMPILER_PRIMARY=gemini
COMPILER_FALLBACK_1=openai_compatible
COMPILER_FALLBACK_2=ollama
COMPILER_WARN_ON_LIMIT=true

# Output Settings
OUTPUT_DIR=./output
IMAGE_FORMAT=sequential
EMBED_DECORATIVE_IMAGES=true
SVG_TO_MERMAID=true
AUTO_DOWNLOAD_IMAGES=true
```

---

## 7. .gitignore Additions Required

Add these to the existing Python .gitignore:
```
# FullMark — never expose these
.env
/workspace/
/test_outputs/
/models/
*.log
/scratch/
```

---

## 8. CLAUDE.md Purpose

`CLAUDE.md` is the master brain file the coding agent reads FIRST.
It must contain:
- This entire architecture
- Per-agent file names and responsibilities
- Fallback rules
- What NOT to do (no paid APIs without user config)
- Output spec
- Coding style rules
- Test requirements per agent

**Status: Content defined here. File not yet created in repo.**

---

## 9. Files Status in Repo

| File | Status |
|---|---|
| `README.md` | ✅ Stub exists |
| `.gitignore` | ✅ Python template exists — needs FullMark additions |
| `LICENSE` | ✅ MIT exists |
| `fullmark_preflight.py` | ❌ Written, NOT pushed yet |
| `CLAUDE.md` | ❌ Not created yet |
| `AGENTS.md` | ❌ Not created yet |
| `.env.template` | ❌ Not created yet |
| `WORKFLOW.md` | ❌ Not created yet |
| All agent code | ❌ Not started |

---

## 10. Pre-flight Script — Status

`fullmark_preflight.py` v1.1 is fully written and tested.
- Groq moved to OPTIONAL (non-blocking)
- OpenRouter added as optional
- .env check added
- Your system result: **22 GO / 1 NO-GO (Groq — intentional)**
- System is confirmed FULL GO for build

**Action needed: Push this file to repo in next session.**

---

## 11. System Environment Confirmed

| Item | Status |
|---|---|
| OS | Windows |
| Python | 3.11.9 |
| ffmpeg | 7.1.1 installed |
| tesseract | v5.5.0 installed |
| All pip packages | ✅ Installed |
| Ollama | ✅ Running locally |
| Gemini key | ⚠️ Exists but expired — needs renewal |
| Disk space | 1341GB available |

---

## 12. Next Session — Exact Steps

### Step 1 — Push Foundation Files (5 minutes)
Push in one commit:
- `fullmark_preflight.py` v1.1
- `CLAUDE.md` (content from this HANDOFF)
- `AGENTS.md`
- `WORKFLOW.md`
- `.env.template`
- Updated `.gitignore`

### Step 2 — Invoke Coding Agent (main build)
Single agent task with CLAUDE.md as context.
Agent builds entire FullMark engine autonomously.
Estimated cost: ~$1.20–$2.00

### Step 3 — Review PR
You review the Pull Request on GitHub.
Click Merge.
Done.

---

## 13. Budget Reality

| Item | Reality |
|---|---|
| Copilot Pro plan | Active ✅ |
| Included credits | 1,500/1,500 exhausted — resets July 1 |
| Additional budget | $10 enabled |
| Spent so far | ~$3–4 (planning conversation) |
| Remaining | ~$6–7 |
| Needed for execution | ~$1.50–$2.50 |
| Buffer remaining after build | ~$4–5 |

---

## 14. Phase 2 — VS Code Extension (After Core Engine)

- Right-click folder → Convert to Markdown with FullMark
- URL list input panel
- Model selector dropdown
- Progress panel per file
- Output folder picker
- Publishable to VS Code Marketplace

---

## 15. Key Decisions Locked

| Decision | Value |
|---|---|
| No paid APIs forced on user | ✅ Always free path available |
| Graceful degradation | ✅ Every component has fallback |
| No Azure/Microsoft dependencies | ✅ Fully independent |
| OpenAI-compatible universal interface | ✅ One SDK covers all providers |
| Base64 for decorative images | ✅ No external image files |
| Sequential naming for data images | ✅ image-001.jpg, image-002.jpg |
| SVG → Mermaid in output | ✅ No binary images for diagrams |
| Whisper runs locally | ✅ No API key needed for transcription |
| Pre-flight script as onboarding | ✅ Single command confirms ready |

---
*Generated: Session 1 — Planning Complete*
*Next: Session 2 — Execution*
