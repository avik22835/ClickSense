// ClickSense side panel — port of side_panel.ts
// Exact message type string values from messaging_defs.ts preserved.

const PANEL_PORT = 'side-panel-2-agent-controller';
const BACKEND_KEY = 'backendUrl';

// Exact string values from messaging_defs.ts
const FROM_BG = {
  READY:     'agentControllerReady',
  STARTED:   'taskStarted',
  CANDIDATE: 'actionCandidate',
  HISTORY:   'taskHistoryEntry',
  ENDED:     'taskEnded',
  ERROR:     'error',
  NOTIFY:    'notification',
};
const TO_BG = {
  START:     'mustStartTask',
  KILL:      'mustKillTask',
  APPROVED:  'monitorApproved',
  REJECTED:  'monitorRejected',
  USER_MSG:  'userMessage',
  KEEPALIVE: 'keepAlive',
};

// ── DOM references ─────────────────────────────────────────────────────────────
const taskSpecField   = document.getElementById('task-spec');
const startButton     = document.getElementById('start-agent');
const stopButton      = document.getElementById('end-task');
const stepCard        = document.getElementById('step-card');
const stepBadge       = document.getElementById('step-badge');
const stepActionType  = document.getElementById('step-action-type');
const stepInstruction = document.getElementById('step-instruction');
const stepElement     = document.getElementById('step-element');
const thinkingDot     = document.getElementById('thinking-dot');
const doneButton      = document.getElementById('done-button');
const skipButton      = document.getElementById('skip-button');
const statusDot       = document.getElementById('status-dot');
const agentStatus     = document.getElementById('agent-status');
const historyList     = document.getElementById('history');
const historyEmpty    = document.getElementById('history-empty');
const stepCount       = document.getElementById('step-count');
const chatSection     = document.getElementById('chat-section');
const chatInput       = document.getElementById('chat-input');
const chatSend        = document.getElementById('chat-send');
const backendUrlInput = document.getElementById('backend-url');
const saveSettingsBtn = document.getElementById('btn-save-settings');

// ── Debug panel refs ──────────────────────────────────────────────────────────
const dbgAction   = document.getElementById('dbg-action');
const dbgElIdx    = document.getElementById('dbg-el-idx');
const dbgElTag    = document.getElementById('dbg-el-tag');
const dbgShot     = document.getElementById('dbg-shot');
const dbgEls      = document.getElementById('dbg-els');
const dbgCtrs     = document.getElementById('dbg-ctrs');
const dbgPlanning = document.getElementById('dbg-planning');

// ── State ─────────────────────────────────────────────────────────────────────
let port      = null;
let stepNum   = 0;
let isRunning = false;

// ── Debug helper ──────────────────────────────────────────────────────────────
function updateDebug(d) {
  if (d.action     !== undefined) dbgAction.textContent   = d.action ?? '—';
  if (d.elIdx      !== undefined) dbgElIdx.textContent    = d.elIdx  ?? '—';
  if (d.elTag      !== undefined) dbgElTag.textContent    = d.elTag  ?? '—';
  if (d.shotKB     !== undefined) dbgShot.textContent     = d.shotKB + ' KB';
  if (d.totalEls   !== undefined) dbgEls.textContent      = d.totalEls;
  if (d.containers !== undefined) dbgCtrs.textContent     = d.containers;
  if (d.planning   !== undefined) dbgPlanning.textContent = d.planning || '—';
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setStatus(text, color = 'gray') {
  agentStatus.textContent = text;
  statusDot.className = `status-dot dot-${color}`;
}

function setRunning(running) {
  isRunning = running;
  startButton.disabled    = running;
  stopButton.disabled     = !running;
  taskSpecField.disabled  = running;
  if (running) {
    chatSection.classList.remove('hidden');
    chatInput.value = '';
  } else {
    stepCard.classList.add('hidden');
    thinkingDot.classList.add('hidden');
    // keep chat section visible after task ends — user may want to ask follow-ups
  }
}

function addHistoryItem(text) {
  stepNum++;
  const li = document.createElement('li');
  li.textContent = text;
  historyList.appendChild(li);
  historyEmpty.classList.add('hidden');
  stepCount.textContent = `${stepNum} step${stepNum !== 1 ? 's' : ''}`;
  historyList.scrollTop = historyList.scrollHeight;
}

function actionLabel(action) {
  switch (action) {
    case 'CLICK':       return 'CLICK';
    case 'TYPE':        return 'TYPE';
    case 'SELECT':      return 'SELECT';
    case 'PRESS_ENTER': return 'PRESS ENTER';
    case 'SCROLL_UP':   return 'SCROLL UP';
    case 'SCROLL_DOWN': return 'SCROLL DOWN';
    case 'HOVER':       return 'HOVER';
    default:            return String(action);
  }
}

function showStepCard(actionInfo) {
  const action        = actionInfo?.action ?? '';
  const planningOutput = actionInfo?.planningOutput ?? '';
  const explanation   = actionInfo?.explanation ?? 'Perform the highlighted action';
  const elementDesc   = actionInfo?.elementData?.description ?? actionInfo?.elementData?.text ?? '';
  const value         = actionInfo?.value ?? '';

  const isNoneAction = action === 'NONE';

  if (isNoneAction) {
    stepBadge.textContent       = 'AI Response';
    stepActionType.textContent  = 'EXPLANATION';
    // Show the concise explanation, not the full planning output (which is verbose AI reasoning)
    stepInstruction.textContent = explanation || planningOutput;
    stepElement.classList.add('hidden');
    doneButton.textContent = 'Got it, continue →';
    skipButton.classList.add('hidden');
  } else {
    const guidance = (planningOutput || explanation) + (value ? `\n\nValue to enter: "${value}"` : '');
    stepBadge.textContent       = `Step ${stepNum + 1}`;
    stepActionType.textContent  = actionLabel(action);
    stepInstruction.textContent = guidance;
    if (elementDesc) {
      stepElement.textContent = elementDesc;
      stepElement.classList.remove('hidden');
    } else {
      stepElement.classList.add('hidden');
    }
    doneButton.textContent = 'I did it ✓';
    skipButton.classList.remove('hidden');
  }

  thinkingDot.classList.add('hidden');
  stepCard.classList.remove('hidden');
  doneButton.disabled = false;
  skipButton.disabled = false;
}

// ── Port connection ───────────────────────────────────────────────────────────
function connect() {
  port = chrome.runtime.connect({ name: PANEL_PORT });
  port.onMessage.addListener(handleMessage);
  port.onDisconnect.addListener(() => {
    port = null;
    if (isRunning) {
      setStatus('Connection lost — please reload the panel', 'red');
      setRunning(false);
    }
    setTimeout(connect, 1500);
  });
}

// ── Message handler ───────────────────────────────────────────────────────────
function handleMessage(msg) {
  switch (msg.type) {

    case FROM_BG.READY:
      setStatus('Ready — enter a goal above to start', 'green');
      break;

    case FROM_BG.STARTED:
      setRunning(true);
      stepNum = 0;
      historyList.innerHTML = '';
      historyEmpty.classList.remove('hidden');
      stepCount.textContent = '0 steps';
      setStatus('Analyzing page...', 'indigo');
      thinkingDot.classList.remove('hidden');
      stepCard.classList.remove('hidden');
      stepActionType.textContent  = '';
      stepInstruction.textContent = 'Analyzing the page and planning the next step...';
      stepElement.classList.add('hidden');
      doneButton.disabled = true;
      skipButton.disabled = true;
      stepBadge.textContent = 'Thinking';
      break;

    case FROM_BG.CANDIDATE:
      setStatus('Your turn — do the highlighted action', 'yellow');
      showStepCard(msg.actionInfo);
      updateDebug({
        action:   msg.actionInfo?.action ?? '—',
        elIdx:    msg.actionInfo?.elementIndex ?? '—',
        elTag:    msg.actionInfo?.elementData?.tagHead ?? '—',
        planning: msg.actionInfo?.planningOutput ?? '',
      });
      break;

    case FROM_BG.HISTORY:
      // background.js sends actionDesc at top level (our fix vs TS bug of msg.entry?.actionDesc)
      if (msg.actionDesc) {
        addHistoryItem(msg.actionDesc);
      }
      setStatus('Analyzing page...', 'indigo');
      thinkingDot.classList.remove('hidden');
      stepBadge.textContent       = `Step ${stepNum + 1}`;
      stepActionType.textContent  = '';
      stepInstruction.textContent = 'Analyzing the next step...';
      stepElement.classList.add('hidden');
      doneButton.disabled = true;
      skipButton.disabled = true;
      break;

    case FROM_BG.ENDED: {
      setRunning(false);
      const endReason = msg.details ?? msg.reason ?? 'Task complete';
      const isSuccess = endReason.toLowerCase().startsWith('task completed');
      setStatus(endReason, isSuccess ? 'green' : 'red');
      stepCard.classList.add('hidden');
      break;
    }

    case FROM_BG.NOTIFY:
      setStatus(msg.msg ?? 'Working...', 'indigo');
      doneButton.disabled = true;
      skipButton.disabled = true;
      thinkingDot.classList.remove('hidden');
      if (msg.dbg) updateDebug({
        shotKB:     msg.dbg.screenshotKB,
        totalEls:   msg.dbg.totalElements,
        containers: msg.dbg.scrollableContainers,
      });
      break;

    case FROM_BG.ERROR:
      setStatus(`Error: ${msg.msg}`, 'red');
      setRunning(false);
      break;
  }
}

// ── Button handlers ───────────────────────────────────────────────────────────
startButton.addEventListener('click', () => {
  const spec = taskSpecField.value.trim();
  if (!spec) { setStatus('Please enter a goal first', 'red'); return; }
  if (!port)  { setStatus('Not connected — please wait', 'red'); return; }
  port.postMessage({ type: TO_BG.START, taskSpecification: spec });
  setStatus('Starting...', 'indigo');
});

function sendChatMessage() {
  const text = chatInput.value.trim();
  if (!text || !port) return;
  port.postMessage({ type: TO_BG.USER_MSG, text });
  setStatus(`You: "${text.slice(0, 60)}${text.length > 60 ? '...' : ''}"`, 'indigo');
  chatInput.value = '';
}

chatSend.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); }
});

stopButton.addEventListener('click', () => {
  if (!port) return;
  port.postMessage({ type: TO_BG.KILL });
  setStatus('Stopping...', 'yellow');
});

doneButton.addEventListener('click', () => {
  if (!port) return;
  doneButton.disabled = true;
  skipButton.disabled = true;
  port.postMessage({ type: TO_BG.APPROVED });
  setStatus('Analyzing next step...', 'indigo');
  thinkingDot.classList.remove('hidden');
  stepBadge.textContent       = `Step ${stepNum + 1}`;
  stepActionType.textContent  = '';
  stepInstruction.textContent = 'Good job! Analyzing the next step...';
  stepElement.classList.add('hidden');
});

skipButton.addEventListener('click', () => {
  if (!port) return;
  skipButton.disabled = true;
  doneButton.disabled = true;
  port.postMessage({ type: TO_BG.REJECTED, feedback: '' });
  setStatus('Re-planning step...', 'indigo');
  thinkingDot.classList.remove('hidden');
  stepBadge.textContent       = 'Re-thinking';
  stepActionType.textContent  = '';
  stepInstruction.textContent = 'Re-planning the step...';
  stepElement.classList.add('hidden');
});

// ── Backend URL settings ──────────────────────────────────────────────────────
function loadSettings() {
  chrome.storage.local.get(BACKEND_KEY, result => {
    if (result[BACKEND_KEY]) backendUrlInput.value = result[BACKEND_KEY];
  });
}

saveSettingsBtn.addEventListener('click', () => {
  const url = backendUrlInput.value.trim();
  if (!url) return;
  chrome.storage.local.set({ [BACKEND_KEY]: url }, () => {
    saveSettingsBtn.textContent = 'Saved!';
    setTimeout(() => { saveSettingsBtn.textContent = 'Save'; }, 1500);
  });
});

// ── Keepalive ─────────────────────────────────────────────────────────────────
setInterval(() => {
  if (port) {
    try { port.postMessage({ type: TO_BG.KEEPALIVE }); } catch {}
  }
}, 20_000);

// ── Init ──────────────────────────────────────────────────────────────────────
loadSettings();
connect();
setStatus('Connecting...', 'gray');
