# FullMark

> *Full Marks — Every source, Perfect Markdown*

Convert **ANY** source format into clean, structured Markdown — with images, videos, diagrams,
and full provenance tracking. One command. No cloud required.

---

## What FullMark Does

FullMark takes files, folders, URLs, videos, images, and archives and converts them into
well-structured Markdown. It auto-detects the source type, routes it to the right conversion
engine, and writes the result with a stable identity so you never convert the same thing twice.

| Category | Formats | How it works |
|---|---|---|
| **Documents** | PDF, DOCX, RTF, TXT, EPUB | Text and tables extracted; scanned PDFs fall back to OCR |
| **Spreadsheets** | XLSX, XLS, CSV, ODS | Each sheet becomes a GFM pipe table |
| **Presentations** | PPTX, ODP | Slide titles, text blocks, and speaker notes |
| **Notebooks** | IPYNB | Markdown cells as-is; code cells in fenced blocks; outputs as text |
| **Email** | MSG (Outlook), EML | Headers + body; HTML email → Markdown |
| **Images** | JPG, PNG, BMP, TIFF, WebP | OCR text extraction (Tesseract → EasyOCR fallback); table images → GFM tables; decorative images embedded as base64 or described by vision LLM |
| **SVG** | SVG | Shapes and paths parsed → Mermaid diagram code block; text elements as bullet list |
| **Video** | MP4, AVI, MOV, MKV, WEBM | Audio → Whisper transcription; frames extracted every 10s, upscaled, OCR'd (Tesseract → EasyOCR → vision LLM fallback); combined into structured Markdown |
| **Audio** | MP3, WAV, M4A | Whisper transcription with `[MM:SS]` timestamps |
| **Web** | HTTP/HTTPS URLs, HTML, RSS, YouTube | Page content + images → Markdown; SVG logos detected by content-type; YouTube transcripts; RSS entries as numbered list |
| **Archives** | ZIP | Auto-unpacked; each file routed to the right agent individually |
| **URL Lists** | TXT, DOCX, XLSX, CSV | One URL per line/cell — each fetched and converted; non-URL lines skipped |
| **Source Code** | `.py` `.js` `.ts` `.go` `.rs` `.java` `.c` `.cpp` `.cs` `.rb` `.php` `.sh` `.sql` `.json` `.yaml` `.toml` `.tf` and [50+ more](#source-code-and-config-files) | Each file becomes a syntax-highlighted fenced code block |
| **GitHub Repos** | `https://github.com/owner/repo` | Full repo tree via GitHub API — no git clone needed |

Every output file carries:
- **YAML front matter** — source URL/path, conversion timestamp, agent name, and a stable `source_id`
- **Provenance footnote** — at the bottom of every file so the origin travels with the document

Files over 120,000 characters are split into `name_001.md`, `name_002.md`, etc.

---

## Before You Clone — Run the Prerequisite Check

Many computers have Python, ffmpeg, or Tesseract installed but **not on their system PATH**.
This means commands like `python`, `ffmpeg`, or `tesseract` might fail even though the software
is physically installed.

**Create a `test.py` file anywhere on your machine and run it first:**

```python
# test.py — paste this and run: python test.py
import shutil, sys

tools = {
    "python":    sys.executable,
    "ffmpeg":    shutil.which("ffmpeg"),
    "tesseract": shutil.which("tesseract"),
}

print(f"Python version : {sys.version}")
for name, path in tools.items():
    status = "✓  found" if path else "✗  NOT FOUND (may need PATH fix)"
    print(f"{name:12} {status}  {path or ''}")
```

> ⚠ A tool showing as "NOT FOUND" here might still be installed — it just isn't on your PATH.
> See the [system binaries](#system-binaries) section for install links.

---

## Python Version

FullMark requires **Python 3.11 or higher**. Check your version:

```bash
python --version
```

If you have multiple Python versions installed, use `py -3.11` on Windows to select explicitly.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/tmprabubiz/fullmark.git
cd fullmark
```

### 2. Create a virtual environment (recommended)

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

Optional extras (install only what you need):

```bash
pip install pymupdf        # enhanced PDF extraction
pip install xlrd           # legacy .xls support
pip install cairosvg       # SVG → raster for vision fallback
```

### 4. System binaries

These are **not** Python packages — install them separately:

| Tool | Purpose | Download |
|---|---|---|
| **ffmpeg** | Video/audio extraction | https://ffmpeg.org/download.html |
| **Tesseract OCR** | Image text extraction | https://github.com/UB-Mannheim/tesseract/wiki (Windows) |

After installing, confirm they are on your PATH:

```bash
ffmpeg -version
tesseract --version
```

If either command fails, add the install directory to your system PATH, or set the full path in `.env`:

```dotenv
FFMPEG_PATH=C:\FFmpeg\bin\ffmpeg.exe
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### 5. Configure your environment

```bash
# Windows
copy .env.template .env

# macOS / Linux
cp .env.template .env
```

Then open `.env` in any text editor. Everything is optional — FullMark always has a free fallback path.

### 6. Verify everything is ready

```bash
python fullmark_preflight.py
```

---

## Usage

### Convert a single file

```bash
python fullmark_cli.py report.pdf
python fullmark_cli.py presentation.pptx
python fullmark_cli.py lecture.mp4
python fullmark_cli.py diagram.svg       # → Mermaid code block
python fullmark_cli.py screenshot.png    # → OCR extracted text
```

### Convert a URL

```bash
python fullmark_cli.py https://example.com/article
```

Web pages are converted with images intact:

- Raster images (JPG/PNG/WebP) → OCR run, text extracted into the document
- SVG images (logos, icons) → content-type detected, saved as `.svg`, converted to Mermaid or text bullets
- Decorative images with no extractable text → base64-embedded inline

When you run a URL for the first time, FullMark asks whether to follow links:

```
Source: https://example.com/docs
Single-page conversion by default (no link following).
Follow links on this page and convert multiple pages? [y/N]:
```

Type `n` (or just press Enter) for a single page. Type `y` to see an estimated page count and time before confirming a crawl.

### Convert a YouTube video

```bash
python fullmark_cli.py https://www.youtube.com/watch?v=VIDEO_ID
```

### Convert a video or audio file

```bash
python fullmark_cli.py lecture.mp4
python fullmark_cli.py interview.mp3
```

Output structure:

```markdown
## Scene 1 — [00:00]

[Transcript for this time segment...]

[Frame OCR text if present]

## Scene 2 — [01:42]
...
```

Whisper runs **locally** — no audio is sent to any cloud service.
Set model size with `--whisper-model tiny|base|small|medium|large` (default: `base`).

**Video frame OCR pipeline** (fully local, no API required):

| Step | Tool | Notes |
|---|---|---|
| 1. Frame extraction | ffmpeg | Every `VIDEO_FRAME_INTERVAL` seconds (default: 10s) |
| 2. Upscale | Pillow LANCZOS | Frames narrower than 1280px are upscaled before OCR |
| 3. OCR primary | Tesseract | Best for text-heavy slides and screen recordings |
| 4. OCR fallback | EasyOCR | Catches stylised fonts and graphics that Tesseract misses |
| 5. Vision LLM fallback | VISION_CHAIN | **Only if both OCR tools return empty** — e.g. hand-drawn diagrams or decorative slides. Disabled by default. Enable by setting `VISION_CHAIN` in `.env`. |

Tune extraction with `.env` settings:

```dotenv
VIDEO_FRAME_INTERVAL=10    # seconds between sampled frames (default: 10)
WHISPER_MODEL=base         # tiny | base | small | medium | large
```

### Manual vision extraction tool (advanced / optional)

For cases where the standard OCR pipeline is insufficient — such as very
low-resolution videos that cannot be usefully upscaled, or videos consisting
entirely of diagrams with no machine-readable text — a standalone script is
included:

```bash
python video_vision_extractor.py "input/lecture.mp4"
```

This sends each unique frame to an **OpenAI vision model** (GPT-4o-mini by
default) and writes a separate `_Video.md` file alongside the main transcript.
It requires `OPENAI_API_KEY` in your `.env`.

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_VISION_MODEL=gpt-4o-mini   # or gpt-4o for higher accuracy
```

Key options:

```bash
# Skip PySceneDetect (much faster for long videos — uses fixed-interval only)
python video_vision_extractor.py lecture.mp4 --skip-scene-detect

# Adjust sampling density (lower = more frames)
python video_vision_extractor.py lecture.mp4 --interval 10 --hash-threshold 10

# Preview which frames would be sent without spending any API tokens
python video_vision_extractor.py lecture.mp4 --dry-run --skip-scene-detect
```

> **Cost note:** GPT-4o-mini vision at `detail: high` costs roughly $0.001–$0.003
> per frame. A 1-hour lecture at 10s intervals ≈ 300 unique frames ≈ $0.30–$0.90.
> The standard OCR pipeline (Tesseract + EasyOCR) is completely free and should be
> tried first — it handles most screen-recording and slide-deck videos well.

### Convert everything in a folder

```bash
python fullmark_cli.py ./my_documents/
```

### Use the `input/` folder (no-argument mode)

Place files into `input/` and run with no arguments:

```bash
python fullmark_cli.py
```

FullMark scans `input/` and converts everything it finds.

### Convert a list of URLs

Create a `.txt` file with one URL per line:

```
https://example.com/page-one
https://example.com/page-two
https://docs.python.org/3/library/os.html
```

Save as `input/urls.txt` and run:

```bash
python fullmark_cli.py input/urls.txt
```

### Crawl a site recursively

```bash
python fullmark_cli.py https://example.com/docs --follow-links --crawl-depth 2 --max-pages 30 --crawl-delay 2
```

> ⚠ Large crawls can consume significant LLM tokens. Start with `--max-pages 10` to sample first.
> Interrupted runs resume automatically — already-converted sources are skipped.

### Convert a GitHub repository — no clone needed

```bash
# Entire repo
python fullmark_cli.py https://github.com/owner/repo

# Specific branch
python fullmark_cli.py https://github.com/owner/repo/tree/main

# Just a subdirectory (recommended for large repos)
python fullmark_cli.py https://github.com/owner/repo/tree/main/src
```

Output contains the repo tree overview, all text files grouped by directory in syntax-highlighted fenced code blocks, and binary files noted but not embedded.

**Rate limits:**

| Mode | Limit |
|---|---|
| Unauthenticated | 60 API requests/hour |
| With `GITHUB_TOKEN` | 5,000 API requests/hour |

```dotenv
GITHUB_TOKEN=ghp_yourTokenHere
```

Get a free token at [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes needed for public repos.

---

### Source code and config files

```bash
python fullmark_cli.py ./my-project/
```

Supported code/config extensions (50+):

| Category | Extensions |
|---|---|
| Python | `.py` `.pyw` `.pyi` |
| JavaScript / TypeScript | `.js` `.mjs` `.cjs` `.jsx` `.ts` `.tsx` |
| JVM | `.java` `.kt` `.scala` `.groovy` |
| C family | `.c` `.h` `.cpp` `.cs` |
| Systems | `.go` `.rs` `.swift` `.zig` `.dart` |
| Scripting | `.rb` `.php` `.pl` `.lua` `.r` |
| Shell | `.sh` `.bash` `.ps1` `.bat` `.cmd` |
| Data / config | `.json` `.yaml` `.toml` `.ini` `.cfg` `.xml` |
| Database | `.sql` `.graphql` `.proto` |
| Infrastructure | `.tf` `.tfvars` `.bicep` `.nix` |
| Web front-end | `.css` `.scss` `.vue` `.svelte` |
| Docs-as-code | `.rst` `.mdx` |
| Misc | `.dockerfile` `.gitignore` `.editorconfig` `.lock` |

### All CLI options

```
python fullmark_cli.py --help

Arguments:
  SOURCE               File, directory, or URL (optional — omit to use input/)

Options:
  -o, --output DIR     Output directory (default: ./output)
  -w, --whisper-model  Whisper model: tiny|base|small|medium|large
  -v, --verbose        Show debug logs
  --follow-links       Follow hyperlinks found on URL sources
  --crawl-depth N      Link-hop depth (default: 1)
  --crawl-delay SECS   Sleep between requests (default: 2.0)
  --max-pages N        Hard cap on crawled pages (default: 50)
  --force              Reconvert even if already in conversion_log.json
  --version            Show version
```

---

## Conversion Log and Deduplication

FullMark tracks every conversion in two files inside `output/`:

| File | Purpose |
|---|---|
| `conversion_log.json` | Machine-readable dedup index — the tool reads this |
| `conversion_log.md` | Human-readable summary table with source ID column |
| `conversion_skipped.log` | Plain-text log of every skipped source with date, file location, and how to reconvert |

### Deduplication is on by default

Re-running FullMark on the same source is **automatically skipped** — no flag needed.
Every source gets a stable `source_id` (`fm-<16hex>`) computed from its content:

| Source type | Identity basis |
|---|---|
| URL | SHA256 of normalised URL — tracking params stripped (`utm_*`, `fbclid`, `gclid`, `ref`), `.git` suffix removed, trailing `/` removed |
| File < 10 MB | SHA256 of full file bytes — same file under a different name is detected |
| File ≥ 10 MB (video/audio) | SHA256 of first 4 MB — fast fingerprint without reading the whole file |

This means `https://example.com/page?utm_source=newsletter` and `https://example.com/page`
produce the **same** `source_id` and are treated as the same source.

### Skip notices — always know what was skipped

When a source is skipped, a notice is appended to `output/conversion_skipped.log`:

```
[2026-06-07 21:47:00 UTC] SKIPPED — already converted
  Source    : https://docs.cloud.google.com/managed-spark/docs
  ID        : fm-5003ea12a85b9f75
  Converted : 2026-06-06 21:47:01 UTC
  Output    :
    output\doc_managed-spark_docs\doc_managed-spark_docs.md
  To reconvert : fullmark_cli.py https://... --force
  To delete & redo: delete the output file(s) above, then run again
```

The skip log is plain text — easy to grep by date, filename, or source ID.

### Deleted output = automatic reconversion

If you **delete an output `.md` file**, FullMark detects that the file is gone and
reconverts automatically — **no `--force` flag needed**. The dedup check verifies
files actually exist on disk, not just that they appear in the log.

Workflow for replacing an output:
1. Delete the `.md` file in `output/`
2. Run `python fullmark_cli.py <source>` — FullMark reconverts without objection

### Force reconversion (output file still exists)

```bash
python fullmark_cli.py https://example.com/article --force
```

Or set for a whole batch run:

```dotenv
FORCE_RECONVERT=true
```

---

## Provenance — Every Output Carries Its Origin

Every converted `.md` file has a provenance trail built in so the source and identity
travel with the document wherever it goes.

**YAML front matter** (top of every file):

```yaml
---
source: https://docs.cloud.google.com/managed-spark/docs
converted: 2026-06-07T10:22:33Z
agent: WebAgent
source_id: fm-5003ea12a85b9f75
---
```

**Footnote** (bottom of every file / last segment):

```
---
*Converted by [FullMark](https://github.com/tmprabubiz/fullmark) · source: `https://...` · id: `fm-5003ea12a85b9f75`*
```

Copy the file into a knowledge base, share it, or embed it in a document store — the
origin is always traceable. The `source_id` ties the output back to the log entry.

---

## Image Handling in Detail

| Image type | What happens |
|---|---|
| **Photo / screenshot with text** | Tesseract OCR → text blocks; aligned columns → GFM table |
| **SVG logo / icon** | Content-type detected from HTTP header (not blindly saved as `.jpg`); shapes → Mermaid code block; `<text>` elements → bullet list |
| **Decorative image (no text)** | Base64-embedded inline or described by vision LLM |
| **Web page images** | Downloaded alongside the page; extension set from `Content-Type` header with byte-sniff fallback (PNG magic, JPEG `FF D8`, SVG `<svg` tag) |

OCR pipeline: **Tesseract** → **EasyOCR** fallback → embed if both fail.

---

## Video and Audio in Detail

```
MP4 / AVI / MOV / MKV / WEBM
  └─ ffmpeg extracts audio
       └─ Whisper (local, free) → timestamped transcript
  └─ PySceneDetect finds scene changes
       └─ opencv extracts one frame per scene → ImageAgent OCR
  └─ CompilerAgent merges transcript + frame OCR → structured Markdown

MP3 / WAV / M4A
  └─ Whisper → [MM:SS] timestamped Markdown
```

Whisper runs fully locally — no audio leaves your machine.

---

## LLM Configuration (optional)

FullMark uses an LLM to structure video/audio transcripts and describe decorative images.
**Entirely optional** — if you have no API keys, it falls back to mechanical formatting.

### Provider chain in `.env`

```dotenv
# Try left-to-right; first to respond wins
COMPILER_CHAIN=openrouter_free,groq,cerebras,gemini,ollama
VISION_CHAIN=gemini,openai,anthropic,openrouter_free,ollama
```

### Provider tiers

| Tier | Providers | Cost |
|---|---|---|
| **Free APIs** | OpenRouter (free models), Groq, Cerebras, NVIDIA, Gemini free, Mistral free | Free |
| **Low-cost** | DeepSeek, Together AI, Fireworks, Cohere | Pay-per-use, cheap |
| **Premium** | OpenAI, Anthropic, Gemini Pro | Pay-per-use |
| **Local / offline** | Ollama (any model you've pulled) | Free |

```dotenv
PROVIDER_MAX_RETRIES=2    # retries per provider on 429 before moving on
PROVIDER_RETRY_DELAY=5    # seconds (exponential: 5s, 10s)
```

---

## Output Structure

```
output/
  report.md                         ← single file (< 120k chars)
  big_document_001.md               ← auto-segmented (> 120k chars)
  big_document_002.md
  doc_managed-spark_docs/
    doc_managed-spark_docs.md       ← web conversion in subfolder
    image-001.svg                   ← companion images, correct extension
    image-002.png
  git_owner_repo/
    git_owner_repo_001.md           ← large repo, 3 segments
    git_owner_repo_002.md
    git_owner_repo_003.md
  conversion_log.json               ← machine-readable dedup index
  conversion_log.md                 ← human-readable summary table with source_id
  conversion_skipped.log            ← skip notices: date, file, how to reconvert
```

---

## Running in a Terminal

FullMark is designed to run in a **Command Prompt or PowerShell window** — not by double-clicking.

```powershell
cd G:\fullmark
python fullmark_cli.py input/
```

---

## Long Sessions and Logging

```bash
# Windows PowerShell — capture everything to a file
python fullmark_cli.py ./docs/ 2>&1 | Tee-Object -FilePath run.log

# Bash / macOS / Linux
python fullmark_cli.py ./docs/ 2>&1 | tee run.log
```

**Verbose mode** — see every routing decision, provider attempt, and retry:

```bash
python fullmark_cli.py report.pdf -v
```

---

## Architecture

```
ORCHESTRATOR  (extension + MIME routing, dedup, source_id, footnote)
    │
    ├── DocumentAgent   → PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    ├── CodeAgent       → .py .js .ts .go .rs .java .json .yaml .toml + 50 more
    ├── WebAgent        → URLs HTML RSS YouTube  +  UrlListAgent
    │       └── ImageAgent  (per downloaded image — OCR / SVG / embed)
    ├── ImageAgent      → JPG PNG SVG BMP TIFF WebP  (Tesseract → EasyOCR → base64)
    ├── VideoAgent      → MP4 AVI MOV MP3 WAV M4A   (ffmpeg + Whisper + PySceneDetect)
    │       └── CompilerAgent  (LLM merge of transcript + frame OCR)
    └── RepoAgent       → https://github.com/owner/repo  (GitHub Trees API, no clone)
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

147 tests, all mocked — no internet connection or external tools required.

---

## Project Structure

```
fullmark/
  __init__.py          ← AgentError, FullMarkError
  orchestrator.py      ← routing, dedup, source_id injection, output writing
  agents/
    document_agent.py  ← PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    code_agent.py      ← source code + config files (50+ extensions)
    web_agent.py       ← URLs HTML RSS YouTube; image content-type detection
    image_agent.py     ← raster OCR + SVG→Mermaid
    video_agent.py     ← Whisper + scene detection + frame OCR
    compiler_agent.py  ← LLM merge of transcript + frame data
    repo_agent.py      ← GitHub repo → Markdown (no clone, GitHub Trees API)
  utils/
    model_client.py    ← provider fallback chain (Gemini → OpenAI-compat → Ollama)
    markdown_utils.py  ← front matter, inject_source_id, append_footnote, GFM tables
    file_utils.py      ← extension detection, ZIP unpacking, URL naming
    metadata_logger.py ← JSON + Markdown log, dedup, skip notices
    crawler.py         ← recursive URL crawler (BFS, depth/delay/domain control)
tests/                 ← pytest suite (147 tests)
fullmark_cli.py        ← CLI entry point
fullmark_preflight.py  ← system dependency checker
.env.template          ← configuration template
```

---

## License

MIT © tmprabubiz
