# ClickSense

ClickSense is a Chrome extension that acts as a real-time AI copilot for browser tasks — you describe a goal in plain English ("set up Firestore for my project"), and the AI analyses the current page, tells you exactly what to do next and why, highlights the precise element to interact with, and moves to the next step once you've done it. The user always stays in control; the AI does the reasoning, the human does the clicking.

Under the hood, the extension is built on Chrome Manifest V3 with a service worker as the central orchestrator — it injects a content script into the active page on demand to recursively walk the DOM across iframes, collecting every interactive element (buttons, links, inputs, selects, scrollable containers) with coordinates, dimensions, and semantic descriptions. Full-page screenshots are captured using the Chrome DevTools Protocol rather than the standard screenshot API, which expands the viewport to 5× its height before capture so the AI sees content below the fold. Scroll actions are also executed via CDP's `Input.dispatchMouseEvent`, generating `isTrusted: true` browser-level events — necessary because SPAs like GCP Console run on Polymer and reject synthetic JavaScript scroll events outright.

The backend is a FastAPI service that receives the screenshot, element list, task description, and action history on every step and runs a deliberate two-phase multimodal AI pipeline: the first call is free-form reasoning where the model analyses the screenshot and plans what to do next, and the second call forces a structured tool call that maps that plan to a specific element index from the candidate list. Separating planning from grounding this way produces meaningfully better element selection accuracy than asking the model to do both in one shot. The action history sent to the backend is a rolling window of the last 15 steps, formatted as SUCCEEDED/FAILED entries with explanations, giving the model enough context to reason about what has already been done without the prompt growing unboundedly.

The system handles edge cases you only discover by actually using it — form pages get a full field-by-field explanation on first visit, then automatically trigger a submit click once the fields are detected as filled; NONE actions surface to the user as an explanation card rather than silently reprompting; the active tab is re-queried at the start of every step so the agent naturally follows the user if they open a link in a new tab; and noop and failure streaks are tracked with hard limits to stop the agent from spinning indefinitely when it's genuinely stuck.

---

## How the AI handles each step

At the start of every step, the system gives the AI two things simultaneously — a full-page screenshot of the browser tab and a structured list of every interactive element on the page: buttons, links, inputs, selects, textareas, scrollable containers, shadow DOM elements, and elements inside iframes, each described with its text content, ARIA attributes, current value if filled, tag type, and exact position and size relative to the viewport. The element list is sorted top-to-bottom, left-to-right, so the model's spatial reasoning aligns with reading order. Together, the screenshot and element list give the AI both a visual understanding of the page and a precise programmatic map of what can be interacted with.

The AI then reasons in two separate passes. The first pass is unconstrained free-form reasoning — the model identifies what page it's on, cross-references the last 15 actions from history (each marked SUCCEEDED or FAILED with an explanation) against the current screenshot to verify what's actually changed, analyses every visible form field or interactive element and its current state, and decides what the next logical action is and why. This planning output is the AI's full chain of thought. The second pass takes that reasoning as context and forces a structured decision: a specific action type chosen from CLICK, TYPE, SELECT, PRESS\_ENTER, SCROLL\_UP, SCROLL\_DOWN, HOVER, NONE, or TERMINATE, mapped to a specific element from the candidate list identified by a letter index (A, B, C...), plus a concise user-facing explanation of what to do and why.

What happens next depends entirely on the action type the AI chose:

- **SCROLL\_UP / SCROLL\_DOWN** — execute automatically. The extension fires browser-level scroll events via CDP, which produces trusted events indistinguishable from real user input (important for apps like GCP Console that actively block synthetic JavaScript scroll events), waits for the animation to settle, then immediately loops back to re-analyse the new page state. The user sees this as a smooth scroll happening on its own.
- **CLICK, TYPE, SELECT, PRESS\_ENTER, HOVER** — surface to the user. The AI highlights the exact target element with a pulsing overlay on the page, shows a step card in the side panel explaining what to do and why, and waits for the user to do it and confirm.
- **NONE** — surfaces as an explanation card. Used when the AI encounters a multi-field form (it explains every single field one by one: what it means, what it currently shows, whether to change it and to what value), when the user asks a mid-task question via the chat box, or when the AI genuinely cannot proceed without more context. The user reads it, acts accordingly, and clicks "Got it, continue".
- **TERMINATE** — ends the task. Only fired when the AI sees a confirmation page or final state that proves the goal was fully accomplished.

The AI also has built-in behavioural rules baked into the prompt. On form pages it distinguishes between first visit (fields empty → explain everything, output NONE) and return visits after the user fills the form (fields filled → skip explanation entirely, output CLICK on the submit button). For navigation it's instructed to always open the main hamburger menu rather than falling back to search bars or product catalogues, which tend to be less reliable paths. Invalid decisions — selecting a non-existent element, choosing scroll when the page is already at its limit, outputting NONE with no meaningful content — are caught by the backend's noop detection layer and silently reprompted rather than surfaced to the user, with streak and total limits to stop the agent if it gets genuinely stuck in a loop.

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
- Scroll actions execute automatically via CDP `Input.dispatchMouseEvent` — generates `isTrusted: true` events, required for SPAs like GCP Console that reject synthetic JS events
- All other actions are shown to the user as a step card — user does it manually, clicks "I did it ✓"
- Tracks active tab at the start of every step so it follows tab switches

**`content.js`** — injected into the page on demand. Two jobs:
- `GET_ELEMENTS`: walks the DOM recursively across iframes and shadow roots, collects every interactive element with coordinates, tag info, and descriptions. Sorted top-to-bottom.
- `HIGHLIGHT`: draws a pulsing overlay on a specific element so the user knows exactly what to interact with

**`side_panel.js`** — the UI logic. Connects to background via a named Chrome port. Handles messages from background (CANDIDATE, HISTORY, NOTIFY, ENDED, etc.) and sends user actions back (START, APPROVED, REJECTED, USER\_MSG).

### Backend side

**`main.py`** — FastAPI server with a single meaningful endpoint: `POST /api/action`. Takes a screenshot, element list, task, history, and returns the next action.

**`llm_engine.py`** — runs a two-phase multimodal AI pipeline per request:
1. **Planning** — free-form text generation. Model sees screenshot + task + history, reasons about the current page state, and decides what to do next.
2. **Grounding** — forces a `browser_action` tool call. Model maps the plan to a specific element from the candidate list. Kept as a separate call to improve element selection accuracy.

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
        ├─ planning call  →  model sees screenshot + prompt, returns reasoning text
        └─ grounding call →  model maps reasoning to browser_action tool call
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
