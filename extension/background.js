// ClickSense background service worker — Python-backed port of AgentController.ts
// Message type string values from messaging_defs.ts preserved exactly.

const PANEL_PORT   = 'side-panel-2-agent-controller';
const BACKEND_KEY  = 'backendUrl';
const DEFAULT_URL  = 'http://localhost:8000';

// Exact string values from AgentController2PanelPortMsgType / Panel2AgentControllerPortMsgType
const TO_PANEL = {
  READY:     'agentControllerReady',
  STARTED:   'taskStarted',
  CANDIDATE: 'actionCandidate',
  HISTORY:   'taskHistoryEntry',
  ENDED:     'taskEnded',
  ERROR:     'error',
  NOTIFY:    'notification',
};
const FROM_PANEL = {
  START:     'mustStartTask',
  KILL:      'mustKillTask',
  APPROVED:  'monitorApproved',
  REJECTED:  'monitorRejected',
  USER_MSG:  'userMessage',
  KEEPALIVE: 'keepAlive',
};

const DEFAULT_MAX_OPS    = 50;
const DEFAULT_MAX_NOOPS  = 20;
const DEFAULT_MAX_FAIL   = 10;
const DEFAULT_MAX_STREAK = 10;

// ── State object ──────────────────────────────────────────────────────────────
const s = {
  status:               'IDLE',
  tabId:                null,
  task:                 '',
  history:              [],   // string[] — sent to backend as planning context
  elements:             [],
  panelPort:            null,
  pendingAction:        null,
  pendingUserMessage:   null,
  pendingRejectionInfo: null,
  lastCycleHadUserMsg:  false,
  opsCount:             0,
  noopCount:            0,
  failureCount:         0,
  failureOrNoopStreak:  0,
  maxOps:               DEFAULT_MAX_OPS,
  maxNoops:             DEFAULT_MAX_NOOPS,
  maxFailures:          DEFAULT_MAX_FAIL,
  maxStreak:            DEFAULT_MAX_STREAK,
};

function resetState() {
  s.status = 'IDLE'; s.tabId = null; s.task = '';
  s.history = []; s.elements = [];
  s.pendingAction = null; s.pendingUserMessage = null; s.pendingRejectionInfo = null;
  s.lastCycleHadUserMsg = false;
  s.opsCount = s.noopCount = s.failureCount = s.failureOrNoopStreak = 0;
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function toPanel(msg) { try { s.panelPort?.postMessage(msg); } catch {} }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Mirrors misc.ts buildGenericActionDesc exactly
function buildGenericActionDesc(action, elementData, value) {
  if (elementData) {
    const v = value ? ` with value: ${value}` : '';
    return `[${elementData.tagHead}] ${elementData.description} -> ${action}${v}`;
  }
  return `Perform element-independent action ${action}`;
}

// Mirrors AgentController history format: "SUCCEEDED-desc; explanation: Y"
function buildHistoryEntry(actionDesc, success, explanation) {
  return `${success ? 'SUCCEEDED' : 'FAILED'}-${actionDesc}; explanation: ${explanation || 'no explanation'}`;
}

// Mirrors TS noop actionDesc strings (pushed to actionsSoFar as FAILED entries)
function buildNoopHistoryEntry(noopReason, action, explanation) {
  let desc;
  switch (noopReason) {
    case 'AI_SELECTED_NONE':
      desc = 'NOOP: ai selected NONE action type'; break;
    case 'INVALID_ELEMENT':
      desc = `NOOP: ai selected invalid option for element to act on with ${action}`; break;
    case 'ACTION_INCOMPATIBLE_WITH_NONE_OF_ABOVE':
      desc = `NOOP: ai selected 'none of the above' option for element selection when action ${action} targets specific element`; break;
    case 'AI_SELECTED_NONSENSICAL_SCROLL':
      desc = `NOOP: AI selected ${action} when scroll is unable to advance`; break;
    default:
      desc = `NOOP: ${noopReason || 'unknown'}`;
  }
  return buildHistoryEntry(desc, false, explanation);
}

function checkLimits() {
  if (s.opsCount > s.maxOps)
    return `exceeded the maximum operations limit of ${s.maxOps}`;
  if (s.noopCount > s.maxNoops)
    return `exceeded the maximum noop limit of ${s.maxNoops}`;
  if (s.failureCount > s.maxFailures)
    return `exceeded the maximum failures limit of ${s.maxFailures}`;
  if (s.failureOrNoopStreak > s.maxStreak)
    return `exceeded the maximum failure-or-noop streak limit of ${s.maxStreak}`;
  return null;
}

// Mirrors AgentController.updateActionHistory — records action, sends TASK_HISTORY_ENTRY
function updateActionHistory(actionDesc, success, explanation) {
  s.history.push(buildHistoryEntry(actionDesc, success, explanation));
  toPanel({ type: TO_PANEL.HISTORY, actionDesc, success, explanation, actionInfo: s.pendingAction });
  s.opsCount++;
  if (success) { s.failureOrNoopStreak = 0; }
  else         { s.failureCount++; s.failureOrNoopStreak++; }
  return checkLimits() !== null; // true = exceeded a limit, should abort
}

// ── Keepalive (prevents service worker from sleeping) ─────────────────────────
let keepaliveTimer = null;
function startKeepalive() {
  if (keepaliveTimer) return;
  keepaliveTimer = setInterval(() => chrome.storage.local.get('__ka__', () => {}), 20_000);
}
function stopKeepalive() {
  if (keepaliveTimer) { clearInterval(keepaliveTimer); keepaliveTimer = null; }
}

// ── Panel port connection ─────────────────────────────────────────────────────
chrome.runtime.onConnect.addListener(port => {
  if (port.name !== PANEL_PORT) return;
  s.panelPort = port;
  startKeepalive();
  toPanel({ type: TO_PANEL.NOTIFY, msg: '*** NEW CODE v7 — SeeAct approach ***' });
  toPanel({ type: TO_PANEL.READY });

  port.onMessage.addListener(msg => {
    handlePanelMsg(msg).catch(err => {
      console.error('[ClickSense bg] error:', err);
      toPanel({ type: TO_PANEL.ERROR, msg: err.message });
      resetState();
    });
  });

  port.onDisconnect.addListener(() => {
    s.panelPort = null;
    resetState();
    stopKeepalive();
  });
});

// ── Panel message handler ─────────────────────────────────────────────────────
async function handlePanelMsg(msg) {
  switch (msg.type) {

    case FROM_PANEL.START: {
      if (s.status !== 'IDLE') return;
      const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
      const tab = tabs[0];
      if (!tab?.id) { toPanel({ type: TO_PANEL.ERROR, msg: 'No active tab found' }); return; }

      s.tabId  = tab.id;
      s.task   = (msg.taskSpecification || '').trim();
      s.history = []; s.elements = [];
      s.opsCount = s.noopCount = s.failureCount = s.failureOrNoopStreak = 0;
      s.pendingRejectionInfo = null; s.pendingUserMessage = null; s.lastCycleHadUserMsg = false;

      const opts = msg.options || {};
      s.maxOps      = Number.isInteger(opts.maxOps)      ? opts.maxOps      : DEFAULT_MAX_OPS;
      s.maxNoops    = Number.isInteger(opts.maxNoops)    ? opts.maxNoops    : DEFAULT_MAX_NOOPS;
      s.maxFailures = Number.isInteger(opts.maxFailures) ? opts.maxFailures : DEFAULT_MAX_FAIL;
      s.maxStreak   = Number.isInteger(opts.maxStreak)   ? opts.maxStreak   : DEFAULT_MAX_STREAK;

      s.status = 'COLLECTING';
      toPanel({ type: TO_PANEL.STARTED });
      await runStep();
      break;
    }

    case FROM_PANEL.KILL:
      resetState();
      toPanel({ type: TO_PANEL.ENDED, reason: 'Stopped by user' });
      break;

    case FROM_PANEL.APPROVED: {
      if (s.status !== 'WAITING_FOR_USER') return;

      // NONE action (AI answered a question) → skip history/counters, just continue
      if (s.pendingAction && s.pendingAction.action !== 'NONE') {
        const actionDesc = buildGenericActionDesc(
          s.pendingAction.action, s.pendingAction.elementData, s.pendingAction.value
        );
        const shouldAbort = updateActionHistory(actionDesc, true, s.pendingAction.explanation);
        if (shouldAbort) {
          toPanel({ type: TO_PANEL.ENDED, reason: checkLimits() });
          resetState();
          return;
        }
      }
      s.pendingAction = null;
      await runStep();
      break;
    }

    case FROM_PANEL.REJECTED: {
      if (s.status !== 'WAITING_FOR_USER') return;

      // Mirrors AgentController.processMonitorRejection exactly:
      // No history entry, no counter increment — stores rejection info for next planning prompt
      if (s.pendingAction) {
        const actionDesc = buildGenericActionDesc(
          s.pendingAction.action, s.pendingAction.elementData, s.pendingAction.value
        );
        s.pendingRejectionInfo =
          `WARNING- The monitor/user rejected your previous planned action: ${actionDesc}`;
        if (msg.feedback) {
          s.pendingRejectionInfo += `;\n They gave the feedback: ${msg.feedback}`;
        }
      }
      s.pendingAction = null;
      await runStep();
      break;
    }

    case FROM_PANEL.USER_MSG:
      s.pendingUserMessage = msg.text;
      if (s.status === 'WAITING_FOR_USER') {
        s.pendingAction = null;
        await runStep();
      }
      // If AI is already thinking, pendingUserMessage is picked up in the next planning cycle
      break;

    case FROM_PANEL.KEEPALIVE:
      break;
  }
}

// ── sendMessage with timeout (avoids hanging Promise) ────────────────────────
function sendMsg(tabId, msg, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`sendMessage timeout: ${msg.type}`)), timeoutMs);
    chrome.tabs.sendMessage(tabId, msg, response => {
      clearTimeout(timer);
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(response);
    });
  });
}

// ── Content script injection (executeScript for flag check, no sendMessage) ───
async function ensureContentScript(tabId) {
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => window.__csLoaded === true,
  });
  if (!res?.result) {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['extension/content.js'] });
    await sleep(300);
  }
}

// ── Screenshot — CDP full-page for AI planning (matches SeeAct's captureFullPageForPlanning)
async function captureScreenshot(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const fallback = () => chrome.tabs.captureVisibleTab(tab.windowId, { format: 'png' });
  try {
    return await Promise.race([
      _cdpFullPage(tabId),
      sleep(8000).then(() => { throw new Error('CDP timeout'); }),
    ]);
  } catch {
    return fallback();
  }
}

async function _cdpFullPage(tabId) {
  // Get viewport dims only — NOT scrollHeight (wrong for SPAs with inner scroll containers)
  const [vpRes] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => ({
      viewportWidth:     window.innerWidth,
      viewportHeight:    window.innerHeight,
      devicePixelRatio:  window.devicePixelRatio || 1,
    }),
  });
  const { viewportWidth, viewportHeight, devicePixelRatio } = vpRes.result;
  const captureHeight = viewportHeight * 5; // large fixed height — forces 100vh containers to expand

  await chrome.debugger.detach({ tabId }).catch(() => {});
  await chrome.debugger.attach({ tabId }, '1.3');
  try {
    await chrome.debugger.sendCommand({ tabId }, 'Emulation.setDeviceMetricsOverride', {
      width: viewportWidth, height: captureHeight, deviceScaleFactor: devicePixelRatio, mobile: false,
    });
    await sleep(250); // wait for CSS reflow after viewport expansion
    // Read actual content height after reflow (not before — SPA containers resize with viewport)
    const [hRes] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => document.documentElement.scrollHeight,
    });
    const actualHeight = Math.min(hRes.result || captureHeight, captureHeight);
    const result = await chrome.debugger.sendCommand({ tabId }, 'Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: viewportWidth, height: actualHeight, scale: 1 },
    });
    await chrome.debugger.sendCommand({ tabId }, 'Emulation.clearDeviceMetricsOverride', {});
    return `data:image/png;base64,${result.data}`;
  } finally {
    await chrome.debugger.detach({ tabId }).catch(() => {});
  }
}

// ── CDP scroll — generates isTrusted:true mouseWheel events (required for GCP/Polymer) ──
async function cdpScroll(tabId, direction, elementIndex) {
  const sign = direction === 'SCROLL_DOWN' ? 1 : -1;
  const el = (elementIndex != null) ? s.elements[elementIndex] : null;

  // Prefer the element's center; fall back to a sensible point near top-left of page
  let cx = 200, cy = 400;
  if (el?.centerCoords?.length === 2) {
    [cx, cy] = el.centerCoords;
  } else if (el) {
    // centerCoords might not exist — try to read rect from content script
    try {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (idx) => {
          const entry = window.__lastElements?.[idx];
          if (!entry?._el?.isConnected) return null;
          const rect = entry._el.getBoundingClientRect();
          return { cx: Math.round(rect.left + rect.width / 2), cy: Math.round(rect.top + rect.height / 2) };
        },
        args: [elementIndex],
      });
      if (r?.result) { cx = r.result.cx; cy = r.result.cy; }
    } catch {}
  }

  await chrome.debugger.detach({ tabId }).catch(() => {});
  await chrome.debugger.attach({ tabId }, '1.3');
  try {
    // Fire 5 mouseWheel ticks — each 200px, 30ms apart — totalling ~1000px of scroll
    for (let i = 0; i < 5; i++) {
      await chrome.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', {
        type: 'mouseWheel',
        x: cx, y: cy,
        deltaX: 0, deltaY: sign * 200,
        modifiers: 0,
      });
      await sleep(30);
    }
    await sleep(200); // let CSS smooth-scroll animation finish before screenshot
  } finally {
    await chrome.debugger.detach({ tabId }).catch(() => {});
  }
}

// ── Main agent loop ───────────────────────────────────────────────────────────
async function runStep() {
  if (!s.panelPort || s.status === 'IDLE') return;

  const hardLimit = checkLimits();
  if (hardLimit) {
    toPanel({ type: TO_PANEL.ENDED, reason: hardLimit });
    resetState();
    return;
  }

  s.status = 'COLLECTING';

  // ── Always follow the currently active tab — user may have switched tabs ──
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (activeTab?.id && activeTab.id !== s.tabId) {
      toPanel({ type: TO_PANEL.NOTIFY, msg: `Switched to new tab: ${activeTab.title?.slice(0, 40) || 'new tab'}`, color: 'indigo' });
      s.tabId = activeTab.id;
      s.elements = []; // old elements are for the wrong tab
    }
  } catch {}

  toPanel({ type: TO_PANEL.NOTIFY, msg: 'Analyzing the page...' });

  // ── Phase 1: Collect page state ───────────────────────────────────────────
  let pageData, screenshot;
  try {
    toPanel({ type: TO_PANEL.NOTIFY, msg: '[1/4] Injecting helper script...' });
    await ensureContentScript(s.tabId);
    await sleep(200);
    toPanel({ type: TO_PANEL.NOTIFY, msg: '[2/4] Collecting page elements...' });
    pageData = await sendMsg(s.tabId, { type: 'GET_ELEMENTS' }, 12_000);
    if (!pageData?.elements) throw new Error('Content script returned no elements');
    s.elements = pageData.elements;
    const nContainers = s.elements.filter(e => e.isScrollableContainer).length;
    toPanel({ type: TO_PANEL.NOTIFY, msg: '[3/4] Taking screenshot...', dbg: {
      totalElements: s.elements.length,
      scrollableContainers: nContainers,
    }});
    screenshot = await captureScreenshot(s.tabId);
    const shotKB = Math.round(screenshot.length * 0.75 / 1024);
    toPanel({ type: TO_PANEL.NOTIFY, msg: '[4/4] Calling AI...', dbg: { screenshotKB: shotKB } });
  } catch (err) {
    console.error('[ClickSense bg] collection error:', err);
    s.failureCount++;
    s.failureOrNoopStreak++;
    if (checkLimits()) {
      toPanel({ type: TO_PANEL.ERROR, msg: 'Too many failures: ' + err.message });
      resetState();
      return;
    }
    toPanel({ type: TO_PANEL.NOTIFY, msg: 'Issue reading page, retrying...' });
    await sleep(2000);
    return runStep();
  }

  const backendUrl = await getBackendUrl();

  // ── Phase 2: Query backend (reprompt loop for noops) ─────────────────────
  while (true) {
    const loopLimit = checkLimits();
    if (loopLimit) { toPanel({ type: TO_PANEL.ENDED, reason: loopLimit }); resetState(); return; }

    s.status = 'THINKING';
    toPanel({ type: TO_PANEL.NOTIFY, msg: 'ClickSense Brain thinking...' });

    // Grab and clear one-shot state before async fetch
    const rejectionInfo    = s.pendingRejectionInfo;
    const userMessage      = s.pendingUserMessage;
    s.pendingRejectionInfo = null;
    s.pendingUserMessage   = null;
    s.lastCycleHadUserMsg  = !!userMessage;

    let result;
    try {
      const resp = await fetch(`${backendUrl}/api/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          screenshot,
          elements:       s.elements,
          candidate_ids:  s.elements.map((_, i) => i),
          task:           s.task,
          history:        s.history.slice(-15),
          viewport:       pageData.viewport,
          user_message:   userMessage  ?? null,
          rejection_info: rejectionInfo ?? null,
          options:        {},
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`Backend ${resp.status}: ${txt.slice(0, 200)}`);
      }
      result = await resp.json();
    } catch (err) {
      console.error('[ClickSense bg] backend error:', err);
      s.failureCount++;
      s.failureOrNoopStreak++;
      if (checkLimits()) {
        toPanel({ type: TO_PANEL.ERROR, msg: 'Too many backend failures. Stopping.' });
        resetState();
        return;
      }
      toPanel({ type: TO_PANEL.NOTIFY, msg: 'Backend issue, retrying...' });
      await sleep(2000);
      continue;
    }

    // TERMINATE — task is done
    if (result.action === 'TERMINATE') {
      toPanel({ type: TO_PANEL.ENDED, reason: 'Task completed: ' + result.explanation });
      resetState();
      return;
    }

    // NOOP — mirrors TS TRY_REPROMPT: push to history, increment counters, loop
    if (result.is_noop) {
      s.noopCount++;
      s.failureOrNoopStreak++;
      s.history.push(buildNoopHistoryEntry(result.noop_reason, result.action, result.explanation));
      toPanel({ type: TO_PANEL.NOTIFY, msg: `AI gave invalid action (${result.noop_reason}), reprompting...` });
      continue;
    }

    // Valid action — build common pendingAction shape
    const elementData = (result.element_index !== null && result.element_index !== undefined)
      ? {
          description: s.elements[result.element_index]?.description || '',
          tagHead:     s.elements[result.element_index]?.tagHead || '',
        }
      : undefined;

    s.pendingAction = {
      action:        result.action,
      elementIndex:  result.element_index,
      elementData,
      value:         result.value,
      explanation:   result.explanation,
      planningOutput: result.planning_output,
      severity:      result.severity || 'SAFE',
    };

    // ── SCROLL: auto-execute immediately, no user confirmation needed ─────────
    if (result.action === 'SCROLL_UP' || result.action === 'SCROLL_DOWN') {
      const dirLabel = result.action === 'SCROLL_DOWN' ? '↓ down' : '↑ up';
      toPanel({ type: TO_PANEL.NOTIFY, msg: `Auto-scrolling ${dirLabel}...` });
      try {
        await cdpScroll(s.tabId, result.action, result.element_index);
      } catch (err) {
        console.warn('[ClickSense bg] cdpScroll failed, continuing anyway:', err);
      }
      const actionDesc = buildGenericActionDesc(result.action, elementData, result.value);
      const shouldAbort = updateActionHistory(actionDesc, true, result.explanation);
      s.pendingAction = null;
      if (shouldAbort) {
        toPanel({ type: TO_PANEL.ENDED, reason: checkLimits() });
        resetState();
        return;
      }
      // Break out of while loop so runStep() re-collects fresh page state
      break;
    }

    // ── All other actions: surface to user for manual execution ───────────────
    if (s.pendingAction.elementIndex !== null && s.pendingAction.elementIndex !== undefined) {
      sendMsg(s.tabId, { type: 'HIGHLIGHT', index: s.pendingAction.elementIndex }, 3000).catch(() => {});
    }
    s.status = 'WAITING_FOR_USER';
    toPanel({ type: TO_PANEL.CANDIDATE, actionInfo: s.pendingAction });
    return;
  }

  // Fell through the while loop (e.g. after an auto-executed scroll) — fetch fresh page state
  await runStep();
}

// ── Helper ────────────────────────────────────────────────────────────────────
async function getBackendUrl() {
  const stored = await chrome.storage.local.get(BACKEND_KEY);
  return stored[BACKEND_KEY] || DEFAULT_URL;
}

// Open side panel when toolbar icon is clicked
chrome.action.onClicked.addListener(tab => {
  chrome.sidePanel.open({ windowId: tab.windowId });
});
