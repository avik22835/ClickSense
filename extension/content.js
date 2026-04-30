// ── Constants & Config ────────────────────────────────────────────────────────

window.__csLoaded = true;

const INTERACTIVE_SELECTORS = [
  'a', 'button', 'input', 'select', 'textarea', 'adc-tab',
  '[role="button"]', '[role="radio"]', '[role="option"]', '[role="combobox"]',
  '[role="textbox"]', '[role="listbox"]', '[role="menu"]', '[role="link"]',
  '[type="button"]', '[type="radio"]', '[type="combobox"]', '[type="textbox"]',
  '[type="listbox"]', '[type="menu"]',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable]:not([contenteditable="false"])',
  '[onclick]', '[onfocus]', '[onkeydown]', '[onkeypress]', '[onkeyup]',
  '[checkbox]', '[aria-disabled="false"]', '[data-link]',
];

const SALIENT_ATTRS = [
  'alt', 'aria-describedby', 'aria-label', 'aria-role', 'input-checked',
  'label', 'name', 'option_selected', 'placeholder', 'readonly',
  'text-value', 'title', 'value', 'aria-keyshortcuts',
];

const NO_TEXT_INPUT_TYPES = ['submit', 'reset', 'checkbox', 'radio', 'button', 'file'];

// ── Helpers ───────────────────────────────────────────────────────────────────

function collapseWhitespace(text) {
  return (text || '').replace(/[\r\n]/g, ' ').replace(/\s{2,}/g, ' ');
}

function getFirstLine(text) {
  const firstLine = (text || '').split(/[\r\n]/)[0];
  const segs = firstLine.split(/\s+/);
  return segs.length <= 8 ? firstLine : segs.slice(0, 8).join(' ') + '...';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Iframe Tracking ───────────────────────────────────────────────────────────

class IframeNode {
  constructor(iframe, win, parent = null) {
    this.iframe = iframe;
    this.window = win;
    this.parent = parent;
    this.children = [];
    this.offset = { x: 0, y: 0 };
    if (iframe) {
      const rect = iframe.getBoundingClientRect();
      this.offset = {
        x: rect.left + (parent ? parent.offset.x : 0),
        y: rect.top  + (parent ? parent.offset.y : 0)
      };
    }
  }
}

class IframeTree {
  constructor() {
    this.root = new IframeNode(null, window);
    this.nodes = new Map([[window, this.root]]);
    this._build(this.root);
  }
  _build(node) {
    let doc;
    try { doc = node.window.document; } catch { return; }
    for (const iframe of Array.from(doc.getElementsByTagName('iframe'))) {
      try {
        const win = iframe.contentWindow;
        if (win && !this.nodes.has(win)) {
          const child = new IframeNode(iframe, win, node);
          node.children.push(child);
          this.nodes.set(win, child);
          this._build(child);
        }
      } catch {}
    }
  }
  getOffset(win) { return this.nodes.get(win)?.offset || { x: 0, y: 0 }; }
}

// ── Element Description ───────────────────────────────────────────────────────

function getElementDescription(el) {
  const tagName   = el.tagName.toLowerCase();
  const typeValue = el.getAttribute('type') || '';
  const roleValue = el.getAttribute('role') || '';

  let parentValue = '';
  const parent = el.parentElement;
  if (parent) {
    const pFirst = collapseWhitespace(getFirstLine((parent.innerText || '').trim())).trim();
    if (pFirst) parentValue = `parent_node: [<${pFirst}>] `;
  }

  if (tagName === 'select') {
    const opt = el.options[el.selectedIndex];
    if (opt?.textContent) {
      const allOpts = Array.from(el.options).map(o => o.text).join(' | ');
      return parentValue + 'Selected: ' + collapseWhitespace(opt.textContent.trim()) + ' - Options: ' + allOpts;
    }
  }

  let inputValue = '';
  if ((tagName === 'input' || tagName === 'textarea') &&
      !NO_TEXT_INPUT_TYPES.includes(typeValue) && !NO_TEXT_INPUT_TYPES.includes(roleValue)) {
    inputValue = `INPUT_VALUE="${el.value}" `;
  }

  let text = (el.textContent || '').trim();
  if (text) {
    text = collapseWhitespace(text);
    if (text.length <= 80) return inputValue + text;
    const inner = (el.innerText || '').trim();
    if (inner) return inputValue + collapseWhitespace(inner);
  }

  const attrs = SALIENT_ATTRS
    .map(a => { const v = el.getAttribute(a); return v ? `${a}="${v}"` : ''; })
    .filter(Boolean).join(' ');

  const desc = (parentValue + attrs).trim();
  if (desc) return inputValue + collapseWhitespace(desc);

  const child = el.firstElementChild;
  if (child) {
    const cAttrs = SALIENT_ATTRS
      .map(a => { const v = child.getAttribute(a); return v ? `${a}="${v}"` : ''; })
      .filter(Boolean).join(' ');
    if (cAttrs) return inputValue + collapseWhitespace(parentValue + cAttrs);
  }

  return tagName;
}

// ── Visibility & Grounding ────────────────────────────────────────────────────

function isBuried(el) {
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return true;
  const tag = el.tagName.toLowerCase();
  if (tag === 'select' || (tag === 'input' && el.type === 'checkbox')) return false;
  const points = [
    { x: rect.left + 2,              y: rect.top + 2 },
    { x: rect.right - 2,             y: rect.top + 2 },
    { x: rect.left + 2,              y: rect.bottom - 2 },
    { x: rect.right - 2,             y: rect.bottom - 2 },
    { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
  ];
  const doc = el.ownerDocument;
  for (const p of points) {
    const topEl = doc.elementFromPoint(p.x, p.y);
    if (topEl && (el.contains(topEl) || topEl.contains(el))) return false;
  }
  return true;
}

function isHidden(el) {
  let win;
  try { win = el.ownerDocument?.defaultView; } catch { win = null; }
  win = win || window;
  const style = win.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return true;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return true;
  const inViewport = rect.top >= 0 && rect.left >= 0 &&
                     rect.bottom <= win.innerHeight && rect.right <= win.innerWidth;
  if (inViewport) return isBuried(el);
  return false;
}

// ── Collection Logic ──────────────────────────────────────────────────────────

function collectFromRoot(root, iframeTree, results, seen) {
  const win = root.defaultView || (root.host ? root.host.ownerDocument.defaultView : window);
  const offset = iframeTree.getOffset(win);
  const all = root.querySelectorAll('*');
  for (const el of all) {
    if (seen.has(el)) continue;
    const isInteractive = INTERACTIVE_SELECTORS.some(s => el.matches?.(s)) || el.onclick;
    if (isInteractive && !isHidden(el)) {
      seen.add(el);
      const rect = el.getBoundingClientRect();
      results.push({
        description: getElementDescription(el),
        tagName: el.tagName.toLowerCase(),
        tagHead: el.tagName.toLowerCase() +
          (el.getAttribute('role') ? ` role="${el.getAttribute('role')}"` : '') +
          (el.getAttribute('type') ? ` type="${el.getAttribute('type')}"` : ''),
        width: rect.width, height: rect.height,
        centerCoords: [
          Math.round(rect.left + offset.x + rect.width  / 2),
          Math.round(rect.top  + offset.y + rect.height / 2),
        ],
        isScrollableContainer: false,
        _el: el,
      });
    }
    if (el.shadowRoot) collectFromRoot(el.shadowRoot, iframeTree, results, seen);
    if (el.tagName.toLowerCase() === 'iframe') {
      try {
        const idoc = el.contentDocument || el.contentWindow?.document;
        if (idoc) collectFromRoot(idoc, iframeTree, results, seen);
      } catch {}
    }
  }
}

const MIN_HIDDEN_PX = 100;

function findScrollableContainersInRoot(root, iframeTree, results, seen) {
  let win;
  try { win = root.defaultView || (root.host ? root.host.ownerDocument.defaultView : window); } catch { return; }
  if (!win) win = window;
  const vpWidth  = win.innerWidth;
  const vpHeight = win.innerHeight;
  const offset = iframeTree.getOffset(win);
  let all;
  try { all = root.querySelectorAll('*'); } catch { return; }
  for (const el of all) {
    if (seen.has(el)) continue;
    const doc = el.ownerDocument;
    if (el === doc.body || el === doc.documentElement) continue;
    if (el.scrollHeight <= el.clientHeight + MIN_HIDDEN_PX) continue;
    if (el.clientHeight === 0 || el.clientWidth === 0) continue;
    let style;
    try { style = win.getComputedStyle(el); } catch { continue; }
    const ovY = style.overflowY || '';
    const ov  = style.overflow  || '';
    const scrollable = ovY === 'auto' || ovY === 'scroll' || ovY === 'overlay'
                    || ov  === 'auto' || ov  === 'scroll' || ov  === 'overlay';
    if (!scrollable) continue;
    // Must overlap the visible viewport
    const rect = el.getBoundingClientRect();
    if (rect.right <= 0 || rect.bottom <= 0 || rect.left >= vpWidth || rect.top >= vpHeight) continue;
    seen.add(el);
    const hiddenPx = Math.round(el.scrollHeight - el.clientHeight);
    const label = el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('id') || el.tagName.toLowerCase();
    results.push({
      description: `Scrollable container (${label}) — scroll to reveal hidden content (${hiddenPx}px more below)`,
      tagName: el.tagName.toLowerCase(),
      tagHead: el.tagName.toLowerCase(),
      width: rect.width, height: rect.height,
      centerCoords: [
        Math.round(rect.left + offset.x + rect.width  / 2),
        Math.round(rect.top  + offset.y + rect.height / 2),
      ],
      isScrollableContainer: true,
      _el: el,
    });
    if (el.shadowRoot) findScrollableContainersInRoot(el.shadowRoot, iframeTree, results, seen);
    if (el.tagName.toLowerCase() === 'iframe') {
      try {
        const idoc = el.contentDocument || el.contentWindow?.document;
        if (idoc) findScrollableContainersInRoot(idoc, iframeTree, results, seen);
      } catch {}
    }
  }
}

function getElements() {
  const iframeTree = new IframeTree();
  const seen = new Set();
  const results = [];
  collectFromRoot(document, iframeTree, results, seen);
  results.sort((a, b) => a.centerCoords[1] - b.centerCoords[1] || a.centerCoords[0] - b.centerCoords[0]);
  const containers = [];
  findScrollableContainersInRoot(document, iframeTree, containers, new Set());
  const final = [...results, ...containers];
  lastResults = final;
  return final.map(e => { const c = { ...e }; delete c._el; return c; });
}

// ── Highlight State ───────────────────────────────────────────────────────────
let lastResults = [];
let highlightOverlay = null;
let highlightRAF = null;
let highlightTimeoutId = null;
const HIGHLIGHT_DURATION_MS = 30000;

function hasSpaceOccupyingPseudoElement(el) {
  let win;
  try { win = el.ownerDocument?.defaultView; } catch { return false; }
  if (!win) return false;
  return ['::before', '::after', '::marker', '::placeholder', '::file-selector-button'].some(p => {
    try {
      const content = win.getComputedStyle(el, p).content;
      return content && content !== '' && content !== 'none' && content !== 'normal';
    } catch { return false; }
  });
}

function pickHighlightTarget(el, allEntries) {
  if (!hasSpaceOccupyingPseudoElement(el)) return el;
  const parent = el.parentElement;
  if (!parent) return el;
  let count = 0;
  for (const e of allEntries) {
    if (e._el && parent.contains(e._el)) { count++; if (count > 1) return el; }
  }
  return pickHighlightTarget(parent, allEntries);
}

function getViewportOffsetForElement(el) {
  const offset = { x: 0, y: 0 };
  let win;
  try { win = el.ownerDocument?.defaultView; } catch { return offset; }
  while (win && win !== window.top && win !== window) {
    let frame;
    try { frame = win.frameElement; } catch { break; }
    if (!frame) break;
    const fr = frame.getBoundingClientRect();
    offset.x += fr.left; offset.y += fr.top;
    let parent;
    try { parent = win.parent; } catch { break; }
    if (!parent || parent === win) break;
    win = parent;
  }
  return offset;
}

function clearHighlight() {
  if (highlightOverlay)    { highlightOverlay.remove(); highlightOverlay = null; }
  if (highlightRAF)        { cancelAnimationFrame(highlightRAF); highlightRAF = null; }
  if (highlightTimeoutId)  { clearTimeout(highlightTimeoutId); highlightTimeoutId = null; }
}

async function highlightElement(index) {
  clearHighlight();
  const entry = lastResults[index];
  if (!entry?._el) return;
  const el = pickHighlightTarget(entry._el, lastResults);

  try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch {}
  let scrollWin;
  try { scrollWin = el.ownerDocument?.defaultView; } catch {}
  while (scrollWin && scrollWin !== window.top && scrollWin !== window) {
    let frame;
    try { frame = scrollWin.frameElement; } catch { break; }
    if (!frame) break;
    try { frame.scrollIntoView({ block: 'center', behavior: 'smooth' }); } catch {}
    let par;
    try { par = scrollWin.parent; } catch { break; }
    if (!par || par === scrollWin) break;
    scrollWin = par;
  }
  await sleep(400);

  highlightOverlay = document.createElement('div');
  highlightOverlay.id = 'clicksense-highlight-overlay';
  Object.assign(highlightOverlay.style, {
    position: 'fixed', pointerEvents: 'none', zIndex: '2147483647',
    border: '4px solid #ef4444', borderRadius: '6px', boxSizing: 'border-box',
    boxShadow: '0 0 15px rgba(239,68,68,0.8), inset 0 0 10px rgba(239,68,68,0.4)',
  });
  document.body.appendChild(highlightOverlay);

  const updatePos = () => {
    if (!highlightOverlay || !el) return;
    const rect = el.getBoundingClientRect();
    const off  = getViewportOffsetForElement(el);
    if (rect.top === 0 && rect.bottom === 0) {
      highlightOverlay.style.display = 'none';
    } else {
      highlightOverlay.style.display = 'block';
      highlightOverlay.style.top    = `${rect.top  + off.y - 4}px`;
      highlightOverlay.style.left   = `${rect.left + off.x - 4}px`;
      highlightOverlay.style.width  = `${rect.width  + 8}px`;
      highlightOverlay.style.height = `${rect.height + 8}px`;
    }
    highlightRAF = requestAnimationFrame(updatePos);
  };
  updatePos();

  const styleId = 'clicksense-pulse-style';
  if (!document.getElementById(styleId)) {
    const s = document.createElement('style');
    s.id = styleId;
    s.textContent = `
      @keyframes clicksense-pulse {
        0%,100% { transform:scale(1); opacity:1; }
        50%      { transform:scale(1.02); opacity:0.8; }
      }
      #clicksense-highlight-overlay { animation: clicksense-pulse 1s infinite ease-in-out; }
    `;
    document.head.appendChild(s);
  }

  highlightTimeoutId = setTimeout(clearHighlight, HIGHLIGHT_DURATION_MS);
}

// ── Message Listener ──────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'PING') {
    sendResponse({ ok: true });
    return false;
  }
  if (msg.type === 'GET_ELEMENTS') {
    sendResponse({
      elements: getElements(),
      viewport: {
        width:            window.innerWidth,
        height:           window.innerHeight,
        scrollX:          window.scrollX,
        scrollY:          window.scrollY,
        pageScrollWidth:  document.documentElement.scrollWidth,
        pageScrollHeight: document.documentElement.scrollHeight,
      },
    });
    return false;
  }
  if (msg.type === 'HIGHLIGHT') {
    highlightElement(msg.index);
    sendResponse({ ok: true });
    return false;
  }
  if (msg.type === 'SCROLL_EXECUTE') {
    const entry = lastResults[msg.index];
    const sign  = msg.direction === 'SCROLL_UP' ? -1 : 1;

    // ── Find the best scrollable target ────────────────────────────────────────
    // Prefer a fresh elementFromPoint lookup over the stored _el reference
    // (SPAs like GCP update the DOM between cycles, making _el stale)
    let targetEl = null;

    function findScrollableAncestor(node) {
      while (node && node !== document.documentElement) {
        const st = window.getComputedStyle(node);
        const ovY = st.overflowY || '', ov = st.overflow || '';
        if ((ovY === 'auto' || ovY === 'scroll' || ovY === 'overlay' ||
             ov  === 'auto' || ov  === 'scroll' || ov  === 'overlay') &&
             node.scrollHeight > node.clientHeight) return node;
        node = node.parentElement;
      }
      return null;
    }

    // 1. Try stored _el if still connected
    if (entry?._el?.isConnected) {
      targetEl = entry.isScrollableContainer
        ? entry._el
        : findScrollableAncestor(entry._el.parentElement);
    }

    // 2. Fresh lookup via centerCoords (handles stale _el after SPA DOM updates)
    if (!targetEl && entry?.centerCoords) {
      const [cx, cy] = entry.centerCoords;
      const fresh = document.elementFromPoint(cx, cy);
      if (fresh) targetEl = findScrollableAncestor(fresh) || findScrollableAncestor(fresh.parentElement);
    }

    // ── Execute scroll via all available methods ────────────────────────────────
    if (targetEl) {
      const amount = sign * targetEl.clientHeight * 0.75;

      // Method A: direct scrollTop (synchronous — works for standard overflow)
      targetEl.scrollTop += amount;

      // Method B: scrollBy smooth (CSS-driven — works for most browsers)
      targetEl.scrollBy({ top: amount, behavior: 'smooth' });

      // Method C: WheelEvent at element center (works for SPA/Polymer/React nav panels
      //           that listen to wheel events rather than relying on CSS overflow)
      const rect = targetEl.getBoundingClientRect();
      const cx = rect.left + rect.width  / 2;
      const cy = rect.top  + rect.height / 2;
      const innerEl = document.elementFromPoint(cx, cy) || targetEl;
      innerEl.dispatchEvent(new WheelEvent('wheel', {
        deltaY: sign * 400,
        deltaMode: WheelEvent.DOM_DELTA_PIXEL,
        bubbles: true, cancelable: true,
        clientX: cx, clientY: cy, view: window,
      }));
    } else {
      // Fallback: scroll the page
      window.scrollBy({ top: sign * window.innerHeight * 0.75, behavior: 'smooth' });
    }

    // Wait 500ms for scroll animation before responding
    setTimeout(() => sendResponse({ ok: true }), 500);
    return true;
  }
});
