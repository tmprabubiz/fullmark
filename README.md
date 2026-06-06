# FullMark

> *Full Marks — Every source, Perfect Markdown*

Convert **ANY** source format into a clean, structured Markdown file.
One command. No cloud required.

---

## What FullMark Does

FullMark takes files, folders, URLs, videos, images, and archives and converts them into well-structured Markdown. It auto-detects the source type and routes it to the right conversion engine — you just point it at something and it works.

| Category | Formats | How it works |
|---|---|---|
| **Documents** | PDF, DOCX, RTF, TXT, EPUB | Text and tables extracted; scanned PDFs fall back to OCR |
| **Spreadsheets** | XLSX, XLS, CSV, ODS | Each sheet becomes a GFM pipe table |
| **Presentations** | PPTX, ODP | Slide titles, text blocks, and speaker notes |
| **Notebooks** | IPYNB | Markdown cells as-is; code cells in fenced blocks; outputs as text |
| **Email** | MSG (Outlook), EML | Headers + body; HTML email converted to Markdown |
| **Images** | JPG, PNG, BMP, TIFF, WebP, SVG | OCR text extraction; SVGs converted to Mermaid diagrams; decorative images described by vision LLM or base64-embedded |
| **Video** | MP4, AVI, MOV, MKV, WEBM | Audio extracted → Whisper transcription; scenes detected → frame OCR; combined by LLM |
| **Audio** | MP3, WAV, M4A | Whisper transcription with `[MM:SS]` timestamps |
| **Web** | HTTP/HTTPS URLs, HTML, RSS, YouTube | Page content → Markdown; YouTube transcripts; RSS entries as numbered list |
| **Archives** | ZIP | Auto-unpacked; each file routed to the right agent individually |
| **URL Lists** | TXT, DOCX, XLSX, CSV with one URL per line | Each URL fetched and converted; non-URL lines reported as skipped |
| **Source Code** | `.py` `.js` `.ts` `.go` `.rs` `.java` `.c` `.cpp` `.cs` `.rb` `.php` `.sh` `.sql` `.json` `.yaml` `.toml` `.tf` and [50+ more](#source-code-and-config-files) | Each file becomes a syntax-highlighted fenced code block |
| **GitHub Repos** | `https://github.com/owner/repo` | Full repo tree via GitHub API — no git clone needed |

Output files land in `./output/` by default — one `.md` per source. Files over 120,000 characters are automatically split into `name_001.md`, `name_002.md`, etc.

---

## Before You Clone — Run the Prerequisite Check

Many computers have Python, ffmpeg, or Tesseract installed but **not on their system PATH**. This means commands like `python`, `ffmpeg`, or `tesseract` might fail even though the software is physically installed.

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

> ⚠ **Results may be inconclusive.** A tool showing as "NOT FOUND" here might
> still be installed — it just isn't on your PATH. Verify independently using
> your OS package manager or by checking the installation directory directly.
> See the [system binaries](#system-binaries) section for install links.

---

## Python Version

FullMark requires **Python 3.11 or higher**. It uses:
- `match` statements and structural pattern matching (3.10+)
- `str | None` union type hints without `from __future__ import annotations` in some places
- `tomllib` (stdlib, 3.11+)

Check your version:
```bash
python --version
# or
python3 --version
```

If you have multiple Python versions installed, make sure you're using 3.11+ throughout. On Windows, `py -3.11` selects a specific version explicitly.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/tmprabubiz/fullmark.git
cd fullmark
```

### 2. Create a virtual environment (recommended)

A virtual environment keeps FullMark's dependencies isolated from your system Python:

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Windows (Command Prompt)
python -m venv .venv
.venv\Scripts\activate.bat

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

The `requirements.txt` covers all core packages. Optional extras (for legacy `.xls`, scanned PDF enhancement, SVG rasterisation) are listed as comments at the bottom of the file — install only what you need:

```bash
# Optional extras
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

If either command fails with "not found", add the install directory to your system PATH, or set the full path in your `.env` file:
```
FFMPEG_PATH=C:\FFmpeg\bin\ffmpeg.exe
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### 5. Configure your environment

Rename `.env.template` to `.env`:

```bash
# Windows
copy .env.template .env

# macOS / Linux
cp .env.template .env
```

Or as a single setup line (clone → venv → install → configure):

```bash
git clone https://github.com/tmprabubiz/fullmark.git && cd fullmark && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && copy .env.template .env
```

Then open `.env` in any text editor and add your API keys. Everything in `.env` is optional — FullMark always has a free fallback.

### 6. Verify everything is ready

```bash
python fullmark_preflight.py
```

This checks Python version, required packages, optional packages, and system binaries, and reports what is and isn't available.

---

## Usage

### Convert a single file

```bash
python fullmark_cli.py report.pdf
python fullmark_cli.py presentation.pptx
python fullmark_cli.py lecture.mp4
```

### Convert a URL

```bash
python fullmark_cli.py https://example.com/article
```

### Convert a YouTube video (transcript + timestamps)

```bash
python fullmark_cli.py https://www.youtube.com/watch?v=VIDEO_ID
```

### Convert everything in a folder

```bash
python fullmark_cli.py ./my_documents/
```

### Use the `input/` folder (no-argument mode)

Place any files you want converted into the `input/` folder, then run with no arguments:

```bash
# Drop files into input/ first
python fullmark_cli.py
```

FullMark scans `input/` and converts everything it finds. This is the easiest workflow for batch jobs.

### Convert a list of URLs

Create a `.txt` file with one URL per line:

```
https://example.com/page-one
https://example.com/page-two
https://docs.python.org/3/library/os.html
```

Save it as `input/urls.txt` and run:

```bash
python fullmark_cli.py input/urls.txt
```

Each URL is fetched, converted, and saved as a separate `.md` file using the naming convention `<domain-prefix>_<path>` (e.g. `exa_docs_api_auth.md`).

### Crawl a site recursively

### Crawl a site recursively

```bash
python fullmark_cli.py https://example.com/docs --follow-links --crawl-depth 2 --max-pages 30 --crawl-delay 2
```

> ⚠ Large crawls can consume significant LLM tokens (~30,000 tokens per page).
> Start with `--crawl-depth 1 --max-pages 10` to sample first.
> Use `--crawl-delay` (default 2 seconds) to avoid rate-limiting.

### Convert a GitHub repository — no clone needed

Point FullMark at any public GitHub repo URL and it converts the entire codebase
to a structured Markdown document — **without cloning**, saving disk space and setup time.

```bash
# Entire repo
python fullmark_cli.py https://github.com/owner/repo

# Specific branch
python fullmark_cli.py https://github.com/owner/repo/tree/main

# Just a subdirectory (recommended for large repos)
python fullmark_cli.py https://github.com/owner/repo/tree/main/src
```

Output is a single `owner_repo.md` containing:
- Repo tree overview
- All text files grouped by directory
- Each file in a syntax-highlighted fenced code block
- Binary files noted but not embedded

**How it works (GitHub ToS compliant):**
- Uses the [GitHub Trees API](https://docs.github.com/en/rest/git/trees) — one API call lists every file path
- Fetches raw content via `raw.githubusercontent.com` (CDN, not counted toward API rate limits)
- Only reads — no write/commit/push operations
- Fully within [GitHub's Acceptable Use Policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)

**Rate limits and authentication:**

| Mode | Limit |
|---|---|
| Unauthenticated | 60 API requests/hour (raw fetches not counted) |
| With `GITHUB_TOKEN` | 5,000 API requests/hour |

Get a free token at [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes needed for public repos. Add it to `.env`:
```dotenv
GITHUB_TOKEN=ghp_yourTokenHere
```

**What gets skipped automatically:**
- `node_modules/`, `__pycache__/`, `.venv/`, `dist/`, `build/`
- `*.min.js`, `*.map`, `*.lock` files
- Compiled objects (`.pyc`, `.class`, `.o`, `.exe`)
- Binary files (images, zips — noted in output but not embedded)
- Files over `REPO_MAX_FILE_KB` (default 200 KB)

Add your own skip patterns in `.env`:
```dotenv
REPO_SKIP_PATTERNS=tests/,docs/,examples/
```

**Practical use cases:**
- Use a repo as a reference base without installing it locally
- Feed a codebase into an LLM for analysis or Q&A
- Archive a snapshot of a project's source as readable documentation
- Review an unfamiliar repo quickly without cloning

> ⚠ **Large repos:** Use a subpath (`/tree/main/src`) to limit scope.
> A 500-file repo can produce a very large Markdown file — consider `--output` to a dedicated folder.

---

### Source code and config files

Dropping a local folder of code into FullMark converts every file it recognises:

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

```bash
python fullmark_cli.py ./docs/ --skip-existing
```

FullMark keeps a `conversion_log.json` in the output directory. With `--skip-existing`, any source with a matching content hash is skipped — safe to re-run on large folders.

### All options

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
  --skip-existing      Skip sources already in conversion_log.json
  --version            Show version
```

---

## LLM Configuration (optional)

FullMark uses an LLM to structure video/audio transcripts and describe decorative images. **This is entirely optional** — if you have no API keys, it falls back to mechanical formatting automatically.

### Set up your chain in `.env`

```dotenv
# Try these providers left-to-right; first to respond wins
COMPILER_CHAIN=openrouter_free,groq,cerebras,gemini,ollama

# For image description (photos, illustrations, SVGs with no text)
VISION_CHAIN=gemini,openai,anthropic,openrouter_free,ollama
```

### Provider tiers

| Tier | Providers | Cost |
|---|---|---|
| **Free APIs** | OpenRouter (free models), Groq, Cerebras, NVIDIA, Gemini free, Mistral free | Free |
| **Low-cost** | DeepSeek, Together AI, Fireworks, Cohere | Pay-per-use, cheap |
| **Premium** | OpenAI, Anthropic, Gemini Pro | Pay-per-use |
| **Local / offline** | Ollama (any model you've pulled) | Free, runs on your machine |

Add only the keys for providers you want to use — the rest are simply skipped.

### Rate-limit handling

When a provider returns a 429 / rate-limit error, FullMark automatically waits and retries the same provider (up to `PROVIDER_MAX_RETRIES` times, default 2) before falling to the next provider in the chain:

```dotenv
PROVIDER_MAX_RETRIES=2    # retries per provider before moving on
PROVIDER_RETRY_DELAY=5    # seconds to wait (exponential: 5s, 10s)
```

---

## Running in a Terminal (Important)

FullMark is designed to run in a **Command Prompt or PowerShell window** — not by double-clicking a file or running through an IDE's run button with output hidden.

Run it from a terminal so you can:
- See real-time progress logs as each file is processed
- Watch agent routing decisions (`routing report.pdf → DocumentAgent`)
- Catch any warnings about missing tools or API keys immediately
- Avoid a blank screen with no feedback during long video transcriptions

On Windows, open PowerShell and navigate to the project folder:
```powershell
cd G:\fullmark
python fullmark_cli.py input/
```

---

## Long Sessions and Logging

For large batch jobs (many files, deep crawls), keep these in mind:

**Sleep between requests** — the crawler uses `--crawl-delay` (default 2s). For large crawls on public sites, increase this to 5–10s to be a polite crawler and avoid rate bans.

**Log to a file** — redirect output to capture everything:
```bash
# Windows PowerShell
python fullmark_cli.py ./docs/ 2>&1 | Tee-Object -FilePath run.log

# Bash / macOS / Linux
python fullmark_cli.py ./docs/ 2>&1 | tee run.log
```

**Resuming interrupted runs** — use `--skip-existing`. If a long batch run is interrupted, re-run with the same command plus `--skip-existing` and it will pick up where it left off using the content hash log.

**Verbose mode** — add `-v` to see every routing decision, provider attempt, and retry:
```bash
python fullmark_cli.py report.pdf -v
```

---

## API Keys — When to Add Them

You have two options:

**Option A — Test locally first (recommended)**
1. Copy `.env.template` to `.env`
2. Add your API keys to `.env`
3. Run `python fullmark_preflight.py` to confirm everything works
4. Test on a few files: `python fullmark_cli.py test.pdf`
5. Only push to GitHub once you're happy — `.env` is in `.gitignore` and will never be committed

**Option B — Push first, configure on the server**
1. Push the repo to GitHub (no keys committed — `.env` is gitignored)
2. On the deployment machine, copy `.env.template` to `.env` and add keys there
3. Run `python fullmark_preflight.py` on the server to verify

Either approach is fine. The important thing: **never commit `.env`**. The `.gitignore` already excludes it.

---

## Architecture

```
ORCHESTRATOR  (extension + MIME routing)
    │
    ├── DocumentAgent   → PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    ├── CodeAgent       → .py .js .ts .go .rs .java .json .yaml .toml + 50 more
    ├── WebAgent        → URLs HTML RSS YouTube  +  UrlListAgent
    ├── ImageAgent      → JPG PNG SVG BMP TIFF WebP  (OCR → vision → base64)
    ├── VideoAgent      → MP4 AVI MOV MP3 WAV M4A   (ffmpeg + Whisper + scenes)
    │           └── CompilerAgent  (LLM merge of transcript + frame OCR)
    └── RepoAgent       → https://github.com/owner/repo  (GitHub Trees API, no clone)
```

Every agent exposes `convert(source) -> str`. The orchestrator detects type, routes, and writes output. ZIP archives are unpacked and each entry routed individually.

---

## Output Structure

```
output/
  report.md                  ← single file (< 120k chars)
  big_document_001.md        ← segmented (> 120k chars)
  big_document_002.md
  exa_docs_api_auth.md       ← URL output: domain_path naming
  conversion_log.json        ← machine-readable log of every conversion
  conversion_log.md          ← human-readable summary table
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

147 tests, all mocked — no internet connection or external tools required to run the test suite.

---

## License

MIT — see [LICENSE](LICENSE).

## Project Structure

```
fullmark/
  __init__.py          ← AgentError, FullMarkError
  orchestrator.py      ← routing + output writing
  agents/
    document_agent.py  ← PDF DOCX XLSX CSV PPTX EPUB IPYNB MSG EML RTF TXT
    code_agent.py      ← source code + config files (50+ extensions)
    web_agent.py       ← URLs HTML RSS YouTube
    image_agent.py     ← raster OCR + SVG→Mermaid
    video_agent.py     ← Whisper + scene detection + frame OCR
    compiler_agent.py  ← LLM merge of transcript + frame data
    repo_agent.py      ← GitHub repo → Markdown (no clone, GitHub Trees API)
  utils/
    model_client.py    ← Gemini → OpenAI-compatible → Ollama fallback chain
    markdown_utils.py  ← front matter, GFM tables, base64 embed
    file_utils.py      ← extension detection, ZIP unpacking, URL naming
    metadata_logger.py ← per-conversion JSON + Markdown log
    crawler.py         ← recursive URL crawler (BFS, depth/delay/domain control)
tests/                 ← pytest suite (147 tests)
fullmark_cli.py        ← CLI entry point
fullmark_preflight.py  ← system dependency checker
.env.template          ← configuration template
```

---

## License

MIT © tmprabubiz
