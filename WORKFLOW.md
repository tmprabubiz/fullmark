# WORKFLOW.md — FullMark Execution Workflow

> How FullMark processes a file from input to Markdown output.

---

## End-to-End Flow

```
User Input
    │
    ▼
fullmark_cli.py
    │  parse args, load .env, create OUTPUT_DIR
    ▼
Orchestrator.convert(source)
    │
    ├─ URL? ──────────────────────────► WebAgent.convert(url)
    │                                        │
    ├─ .zip? ─── unpack ─── loop ────────────┤
    │                                        │
    ├─ directory? ─── walk ─── loop ─────────┤
    │                                        │
    └─ file? ─── routing table ─────────────►┤
         │                                   │
         ├─ Document formats ─► DocumentAgent│
         ├─ Image formats ────► ImageAgent   │
         └─ Video/Audio ──────► VideoAgent   │
                                   │         │
                                   ▼         │
                              CompilerAgent──┘
                                   │
                                   ▼
                          Markdown string
                                   │
                                   ▼
                     Write <stem>.md to OUTPUT_DIR
```

---

## Detailed Step-by-Step

### Step 1: CLI Entry
```
python fullmark_cli.py <source> [--output ./output] [--whisper-model base]
```
- Load `.env` with `python-dotenv`
- Create `OUTPUT_DIR` if not exists
- Call `Orchestrator().convert(source)`

### Step 2: Orchestrator Detection

| Check | Action |
|---|---|
| Starts with `http://` or `https://` | → WebAgent |
| Is a `.zip` file | → extract to temp dir → route each file |
| Is a directory | → `os.walk` → route each file |
| Extension in document table | → DocumentAgent |
| Extension in image table | → ImageAgent |
| Extension in video/audio table | → VideoAgent |
| Unknown extension | → log warning → skip |

### Step 3: Agent Execution

Each agent:
1. Reads source file / URL
2. Extracts content using primary tool
3. Falls back to secondary tool if primary fails
4. Formats content as Markdown
5. Adds front matter header
6. Returns Markdown string

### Step 4: Output Writing

For each `(source_path, markdown)` tuple:
1. Determine output filename: `OUTPUT_DIR / Path(source_path).stem + ".md"`
2. Write Markdown string to file (UTF-8)
3. Copy any referenced image files to same directory
4. Log success to stderr

---

## Error Handling Policy

| Scenario | Behavior |
|---|---|
| Agent crashes | Log exception + continue with next file |
| Primary tool missing | Log warning + try fallback tool |
| Fallback tool missing | Log warning + skip that feature |
| No LLM configured | Log warning + output uncompiled content |
| Output dir not writable | Raise `FullMarkError` immediately |
| Unknown file type | Log warning + skip |

---

## Logging Format

All log output goes to **stderr** at these levels:

```
INFO   fullmark.orchestrator — routing <file> → DocumentAgent
DEBUG  fullmark.agents.document — extracted 42 paragraphs from report.pdf
WARNING fullmark.agents.document — pytesseract not available, skipping OCR fallback
ERROR  fullmark.agents.video — ffmpeg not found, cannot process video.mp4
INFO   fullmark.orchestrator — wrote output/report.md (3.2 KB)
```

---

## ZIP Handling Detail

```
input.zip
  ├── report.pdf      → DocumentAgent → report.md
  ├── diagram.svg     → ImageAgent    → diagram.md
  └── video.mp4       → VideoAgent    → video.md

All outputs written to OUTPUT_DIR/input_zip/
```

---

## Pre-flight Checklist (run once before first use)

```bash
python fullmark_preflight.py
```

Checks:
- Python version ≥ 3.11
- ffmpeg on PATH
- tesseract on PATH
- All pip packages importable
- .env file exists
- OUTPUT_DIR writable

---
*WORKFLOW.md generated from HANDOFF.md — Session 2*
