# ClickSense

A Chrome extension that gives you step-by-step AI guidance for browser tasks. You stay in control — the AI analyses the page, tells you what to do next and why, you do it, and it moves on.

Built as a Python-backed port of [SeeAct](https://github.com/OSU-NLP-Group/SeeAct), rewritten from TypeScript to plain JS + FastAPI, with a bunch of improvements on top.

---

## What it actually does

You open the side panel, type a goal like "set up Firestore for my project", and the AI walks you through it step by step. On navigation pages it highlights the exact link or button you need to click. On form pages it explains every single field (what it means, what to set it to) before asking you to fill anything. Scroll actions run automatically. Everything else waits for you to do it.

It follows whichever tab is currently active, so if you open a link in a new tab it picks up there without losing context.

---

## Architecture

```
Chrome Extension (MV3)          Python Backend
─────────────────────          ──────────────
side_panel.html/js/css  ←──►  main.py (FastAPI)
background.js                  llm_engine.py
content.js                     prompts.py
                               models.py
```

### Extension side

**`background.js`** — the service worker and brain of the extension. Runs the full task loop:
- Keeps a single state object `s` (tabId, task, history, elements, pendingAction, counters)
- On each step: injects content script → collects elements → takes CDP screenshot → POSTs to backend → gets action back
- Scroll actions (SCROLL_UP/DOWN) execute automatically via CDP `Input.dispatchMouseEvent` — this generates `isTrusted: true` events, which matters for SPAs like GCP Console that reject synthetic JS events
- All other actions (CLICK, TYPE, etc.) are shown to the user as a step card — user does it manually, clicks "I did it ✓"
- Tracks active tab at the start of every step so it follows tab switches

**`content.js`** — injected into the page on demand. Two jobs:
- `GET_ELEMENTS`: walks the DOM, collects every interactive element (links, buttons, inputs, selects, scrollable containers) with coordinates, tag info, and descriptions. Handles iframes recursively. Returns a flat list.
- `HIGHLIGHT`: draws a pulsing overlay on a specific element so the user knows exactly what to click

**`side_panel.js`** — the UI logic. Connects to background via a named Chrome port (`side-panel-2-agent-controller`). Handles messages from background (CANDIDATE, HISTORY, NOTIFY, ENDED, etc.) and sends user actions back (START, APPROVED, REJECTED, USER_MSG).

### Backend side

**`main.py`** — FastAPI server with a single meaningful endpoint: `POST /api/action`. Takes a screenshot, element list, task, history, and returns the next action.

**`llm_engine.py`** — runs a two-phase Gemini pipeline per request:
1. **Planning** — free-form text generation. AI sees the screenshot + task + history and reasons about what to do next. No tool use forced here so it can think freely.
2. **Grounding** — forces a `browser_action` tool call. AI maps the planned action to a specific element from the candidate list. Keeping this as a separate call (rather than one combined call) significantly improves element selection accuracy.

Extended thinking is disabled (`thinking_budget=0`) and token limits are kept tight so each round-trip stays fast.

**`prompts.py`** — all the prompt logic. Planning prompt includes task, last 15 history entries, viewport scroll info, and optional user message or rejection info. Grounding prompt formats the element list as a labelled multiple-choice question (A, B, C...) with position and size info relative to the viewport.

**`models.py`** — Pydantic schemas for the request/response contract between extension and backend.

### How a single step flows end-to-end

```
background.js (runStep)
  │
  ├─ check active tab, update s.tabId if switched
  ├─ ensureContentScript(tabId)  →  content.js injected if needed
  ├─ sendMsg GET_ELEMENTS        →  content.js walks DOM, returns elements[]
  ├─ captureScreenshot(tabId)    →  CDP: expand viewport, capture PNG, restore
  │
  └─ POST /api/action
        │
        ├─ planning call  →  Gemini sees screenshot + prompt, returns reasoning text
        └─ grounding call →  Gemini maps reasoning to browser_action tool call
              │
              └─ { action, element_index, value, explanation, planning_output }

  ├─ SCROLL     → cdpScroll() fires immediately, loop continues automatically
  ├─ TERMINATE  → send ENDED to panel, task done
  ├─ NONE       → surface as "AI Response" card, user reads and clicks "Got it"
  └─ CLICK/TYPE → send CANDIDATE to panel, highlight element, wait for user
```

---

## Setup

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env`:
```
GEMINI_API_KEY=your_key_here
```

Start the server:
```bash
uvicorn main:app --reload
```

### 2. Extension

1. Open `chrome://extensions`, enable **Developer Mode**
2. Click **Load unpacked**, select the repo root (where `manifest.json` is)
3. Pin the ClickSense icon and click it to open the side panel
4. In the side panel, expand **Backend Settings** and set the URL to `http://localhost:8000`

---

## Tech stack

- Chrome Extension Manifest V3 — service worker, scripting, debugger, sidePanel APIs
- Chrome DevTools Protocol (CDP) — full-page screenshots and trusted scroll events
- FastAPI + Pydantic
- Google Gemini 2.5 Flash (`google-genai` SDK)
- Plain JS on the extension side, no build step needed

---

## Known limitations

- Needs the Python backend running locally — no hosted version
- CDP attaches a debugger to the tab, so you can't have DevTools open on the same tab at the same time
- Flash model occasionally picks the wrong element on dense pages; Pro is more accurate but noticeably slower
