# AGENTS.md — FullMark Agent Specifications

> This file defines the responsibilities, interfaces, and behaviors of each agent in FullMark.
> Read CLAUDE.md first for overall architecture.

---

## Agent Interface Contract

Every agent MUST:

1. Be a class that accepts no constructor arguments (config via `.env`)
2. Expose a `convert(source: str | Path) -> str` public method
3. Return a valid Markdown string (with front matter)
4. Raise `fullmark.AgentError` on unrecoverable failure
5. Use `logging.getLogger(__name__)` — never `print()`
6. Handle its own fallback internally

---

## Orchestrator Agent

**File:** `fullmark/orchestrator.py`
**Class:** `Orchestrator`

### Responsibilities
- Accept any file path, directory, or URL string as input
- Detect input type (extension + MIME)
- Instantiate and call the correct agent
- Handle ZIP archives by unpacking and routing each file
- Collect all outputs and write final `.md` files to `OUTPUT_DIR`
- Log all routing decisions

### Public Methods
```python
def convert(self, source: str | Path) -> list[tuple[str, str]]:
    """Convert source to Markdown. Returns list of (source_path, markdown)."""

def convert_file(self, path: Path) -> str:
    """Convert a single file. Returns markdown string."""
```

### Routing Logic
1. If `source` is a URL string → Web Agent
2. If `source` is a ZIP file → unpack → route each entry
3. If `source` is a directory → walk → route each file
4. Otherwise → look up extension in routing table → call agent

---

## Document Agent

**File:** `fullmark/agents/document_agent.py`
**Class:** `DocumentAgent`

### Supported Formats
PDF, DOCX, RTF, TXT, EPUB, XLSX, CSV, ODS, PPTX, ODP, IPYNB, MSG, EML

### Conversion Pipeline
1. **PDF**: `pdfplumber` → extract text + tables → if text empty → `pytesseract` fallback
2. **DOCX**: `python-docx` → paragraphs + tables + images
3. **XLSX/ODS**: `openpyxl` → each sheet as a GFM table
4. **CSV**: stdlib `csv` → GFM table
5. **PPTX/ODP**: `python-pptx` → slide titles + text + notes
6. **EPUB**: `ebooklib` + `bs4` → chapters in order
7. **IPYNB**: `json` load → cells: markdown as-is, code in fenced blocks, outputs as text
8. **MSG**: `extract-msg` → headers + body
9. **EML**: stdlib `email` → headers + body (HTML body via bs4)
10. **RTF**: `striprtf` → plain text → wrap

---

## Web Agent

**File:** `fullmark/agents/web_agent.py`
**Class:** `WebAgent`

### Supported Inputs
- `http://` or `https://` URLs (general web pages)
- Local `.html` / `.htm` files
- RSS feed URLs (auto-detected by Content-Type or `<rss>` tag)
- YouTube URLs (auto-detected by domain)

### Conversion Pipeline
1. **General URL**: `requests.get` → `bs4` parse → `markdownify` convert
2. **YouTube URL**: `youtube-transcript-api` → transcript + metadata
3. **RSS Feed**: `feedparser` → entries as numbered list with titles + summaries
4. **Local HTML**: read file → same as general URL (skip fetch)

### Image Handling
- Download all `<img>` tags → save as `image-001.jpg`, `image-002.jpg` etc.
- Reference in output as `![description](image-001.jpg)`
- Skip 1×1 tracking pixels (width/height < 5)

---

## Image Agent

**File:** `fullmark/agents/image_agent.py`
**Class:** `ImageAgent`

### Supported Formats
JPG, JPEG, PNG, BMP, TIFF, TIF, WebP, SVG

### Conversion Pipeline

#### Raster Images (JPG, PNG, BMP, TIFF, WebP)
1. Open with `Pillow` → extract EXIF metadata
2. Run `pytesseract` OCR → get text blocks
3. If text blocks detected → format as structured Markdown
4. If table-like structure detected (aligned columns) → convert to GFM table
5. If no text / low confidence → classify as decorative → base64 embed
6. OCR fallback: if `pytesseract` fails → try `easyocr`

#### SVG Images
1. Parse with `lxml`
2. Extract shapes (rect, circle, path, text, line)
3. Identify diagram type (flowchart, graph, timeline)
4. Generate Mermaid diagram code block
5. Fallback: extract all `<text>` elements as bullet list

### Output Format
- Has text: Markdown with extracted text + optional base64 thumbnail
- Decorative/no text: `![filename](data:image/jpeg;base64,...)` embedded
- EXIF present: front matter with camera/date/GPS data

---

## Video Agent

**File:** `fullmark/agents/video_agent.py`
**Class:** `VideoAgent`

### Supported Formats
**Video:** MP4, AVI, MOV, MKV, WEBM
**Audio-only:** MP3, WAV, M4A

### Conversion Pipeline

#### Audio-Only Files
1. Transcribe with `openai-whisper` (local model, free)
2. Format transcript with timestamps as `[MM:SS]` markers
3. Pass to Compiler Agent for structuring

#### Video Files
1. Extract audio track with `ffmpeg`
2. Transcribe audio with `openai-whisper`
3. Detect scene changes with `PySceneDetect` + `opencv-python`
4. Extract one high-res JPEG frame per scene change
5. Run Image Agent OCR on each frame
6. Collect: `{timestamp: str, frame_path: Path, ocr_text: str}`
7. Pass transcript + frame data to Compiler Agent

### Output
- Section per scene with `## Scene N — [MM:SS]`
- Transcript segment for that time range
- OCR text from frame (if any)
- Frame image as `image-001.jpg` reference

---

## Compiler Agent

**File:** `fullmark/agents/compiler_agent.py`
**Class:** `CompilerAgent`

### Responsibilities
- Merge audio transcript + visual OCR data into structured Markdown
- Align by timestamp
- Use LLM to clean up, structure, and deduplicate content
- Fallback: if no LLM available → format mechanically without LLM

### Input
```python
@dataclass
class CompilerInput:
    source: str                     # original filename
    transcript: list[dict]          # [{start: float, text: str}, ...]
    frames: list[dict]              # [{timestamp: float, ocr_text: str, path: str}, ...]
```

### LLM Prompt Strategy
- System: "You are a technical transcription formatter..."
- User: structured JSON of transcript + frame OCR
- Output: clean Markdown document
- Max prompt size: 8000 tokens (chunk if larger)

---
*AGENTS.md generated from HANDOFF.md — Session 2*
