# FullMark

> *Full Marks — Every source, Perfect Markdown*

Convert **ANY** source format into a clean, structured Markdown file.
One command. No cloud required.

---

## Supported Formats

| Category | Formats |
|---|---|
| Documents | PDF, DOCX, RTF, TXT, EPUB |
| Spreadsheets | XLSX, CSV, ODS |
| Presentations | PPTX, ODP |
| Notebooks | IPYNB |
| Email | MSG (Outlook), EML |
| Images | JPG, PNG, BMP, TIFF, WebP, SVG |
| Video | MP4, AVI, MOV, MKV, WEBM |
| Audio | MP3, WAV, M4A (Whisper transcription) |
| Web | HTTP/HTTPS URLs, HTML, RSS feeds, YouTube URLs |
| Archives | ZIP (auto-unpacked, each file routed individually) |

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Check system readiness
python fullmark_preflight.py

# Convert a file
python fullmark_cli.py report.pdf

# Convert a URL
python fullmark_cli.py https://example.com/article

# Convert a YouTube video (transcript)
python fullmark_cli.py https://www.youtube.com/watch?v=VIDEO_ID

# Convert everything in a folder
python fullmark_cli.py ./my_documents/ --output ./output

# Convert a ZIP archive
python fullmark_cli.py bundle.zip
```

Output files are written to `./output/` (configurable via `.env`).

---

## Setup

```bash
# 1. Clone
git clone https://github.com/tmprabubiz/fullmark.git
cd fullmark

# 2. Install Python packages
pip install -r requirements.txt

# 3. Install system binaries
#    ffmpeg  → https://ffmpeg.org/download.html
#    tesseract → https://github.com/UB-Mannheim/tesseract/wiki

# 4. Configure LLM (optional, for video/audio structuring)
cp .env.template .env
# Edit .env — add GEMINI_API_KEY or OPENAI_API_KEY

# 5. Verify everything is ready
python fullmark_preflight.py
```

---

## Architecture

```
ORCHESTRATOR
    │
    ├── DocumentAgent  → PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    ├── WebAgent       → URLs HTML RSS YouTube
    ├── ImageAgent     → JPG PNG SVG BMP TIFF WebP  (OCR + Mermaid)
    └── VideoAgent     → MP4 AVI MOV MP3 WAV M4A   (Whisper + scene OCR)
                └── CompilerAgent  (LLM merge of transcript + frame OCR)
```

All agents have a `convert(source) -> str` interface.
The orchestrator detects file type and routes automatically.
Every component has a free fallback — no paid API is ever required.

---

## LLM Configuration (optional)

FullMark uses an LLM to structure video/audio output.
Priority chain (set in `.env`):

1. **Gemini** (free tier) — `GEMINI_API_KEY`
2. **Any OpenAI-compatible provider** — `OPENAI_API_KEY` + `OPENAI_BASE_URL`  
   Works with OpenRouter, Groq, Mistral, Together AI, LM Studio, etc.
3. **Ollama** (local, fully offline) — `OLLAMA_BASE_URL`
4. **None** — mechanical formatting without LLM (always available)

---

## Running Tests

```bash
python -m pytest tests/ -v
```

71 tests, all mocked — no internet or external tools required for tests.

---

## Project Structure

```
fullmark/
  __init__.py          ← AgentError, FullMarkError
  orchestrator.py      ← routing + output writing
  agents/
    document_agent.py  ← PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    web_agent.py       ← URLs HTML RSS YouTube
    image_agent.py     ← raster OCR + SVG→Mermaid
    video_agent.py     ← Whisper + scene detection + frame OCR
    compiler_agent.py  ← LLM merge of transcript + frame data
  utils/
    model_client.py    ← Gemini → OpenAI-compatible → Ollama fallback chain
    markdown_utils.py  ← front matter, GFM tables, base64 embed
    file_utils.py      ← extension detection, ZIP unpacking
tests/                 ← pytest suite (71 tests)
fullmark_cli.py        ← CLI entry point
fullmark_preflight.py  ← system dependency checker
.env.template          ← configuration template
```

---

## License

MIT © tmprabubiz
