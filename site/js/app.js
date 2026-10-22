// Page wiring: map, language, loading lookup.json, status line, footer and ticker.
import { buildIndex, countryKind, formatCount, maskCidr, exampleIp } from './core.js';
import { createMap } from './map.js';
import { t, lang, setLang, applyStrings, countryText, categoryName } from './i18n.js';

const DEFAULT_DATA = 'https://raw.githubusercontent.com/Psycomy/MikroBlockList/lists/lookup.json';
const NARROW = 700;

const $ = (id) => document.getElementById(id);

/** The page elements the search flow uses. */
export const els = {
  form: $('f'),
  q: $('q'),
  st: $('st'),
  bar: $('bar'),
  r: $('r'),
  retry: $('retry'),
};

/** The map ({comet, wave, project, reduced}). */
export const map = createMap($('map'), { target: () => els.q });

/** The loaded index (null until ready); see buildIndex in core.js. */
export let index = null;

/** Resolves with {CC: [lon, lat]} (empty on failure), for the country comets. */
export const centroids = fetch(new URL('../data/centroids.json', import.meta.url))
  .then((r) => (r.ok ? r.json() : {}))
  .catch(() => ({}));

let resolveReady;
/** Resolves with the index once lookup.json is loaded and indexed (after a Retry if needed). */
export const ready = new Promise((resolve) => { resolveReady = resolve; });

let searchHandler = null;
/** Register the function that runs a search for the query text (Task 7). */
export function onSearch(fn) {
  searchHandler = fn;
}

// --- data URL: ?data=<same-origin relative path> overrides the default (local testing) ---
function dataUrl() {
  const raw = new URLSearchParams(location.search).get('data');
  if (raw && !/^[a-z][a-z0-9+.-]*:/i.test(raw) && !/^[/\\]{2}/.test(raw) && !raw.includes('\\')) {
    try {
      const url = new URL(raw, location.href);
      if (url.origin === location.origin) return url.href;
    } catch { /* fall through to the default */ }
  }
  return DEFAULT_DATA;
}

// Fetch and index in a module worker; on the main thread (after a yield) if workers fail.
function loadInWorker(url) {
  return new Promise((resolve, reject) => {
    let worker;
    try {
      worker = new Worker(new URL('./loader.worker.js', import.meta.url), { type: 'module' });
    } catch (err) {
      reject(Object.assign(new Error('no worker'), { noWorker: true, cause: err }));
      return;
    }
    worker.onmessage = (event) => {
      worker.terminate();
      if (event.data.error) reject(new Error(event.data.error)); else resolve(event.data.index);
    };
    worker.onerror = (event) => {
      event.preventDefault();
      worker.terminate();
      reject(Object.assign(new Error('worker failed'), { noWorker: true }));
    };
    worker.postMessage({ url });
  });
}

const idle = () => new Promise((resolve) => {
  if ('requestIdleCallback' in window) requestIdleCallback(() => resolve(), { timeout: 500 });
  else setTimeout(resolve, 50);
});

async function loadOnMain(url) {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  await idle();
  return buildIndex(data);
}

let status = 'loading';

/** 'loading', 'ready' or 'error'; a 'datastatus' event on document fires on each change. */
export function dataStatus() {
  return status;
}

function setStatus(next) {
  status = next;
  renderStatus();
  document.dispatchEvent(new CustomEvent('datastatus', { detail: next }));
}

function renderStatus() {
  const { st, retry } = els;
  st.setAttribute('aria-live', 'polite'); // loading, ready and error are announced here
  st.classList.remove('bad', 'ok');
  st.classList.toggle('warn', status === 'error');
  retry.hidden = status !== 'error';
  if (status === 'loading') st.textContent = t('loading');
  else if (status === 'error') st.textContent = t('unavailable');
  else if (status === 'ready') {
    st.textContent = t('ready', {
      n: formatCount(index.counts.v4 + index.counts.v6, lang()),
      s: index.sourcesWithData,
    });
  }
}

/** Set the idle status line; the search flow may overwrite #st freely and call this back. */
export function showIdleStatus() {
  renderStatus();
}

async function load() {
  setStatus('loading');
  renderFooter();
  const url = dataUrl();
  // let the map paint its first frames before any network or parsing work
  // (a timeout too: a background tab gets no animation frames)
  await new Promise((resolve) => {
    requestAnimationFrame(() => setTimeout(resolve, 0));
    setTimeout(resolve, 100);
  });
  try {
    let built;
    try {
      built = await loadInWorker(url);
    } catch (err) {
      if (!err.noWorker) throw err;
      built = await loadOnMain(url);
    }
    // structured clone keeps BigInt and Date; check the shape anyway
    if (!built || !built.v4 || !(built.generatedAt instanceof Date)) throw new Error('bad index');
    index = built;
    resolveReady(index);
    setStatus('ready');
    renderFooter();
    setExample();
    startTicker();
  } catch (err) {
    console.warn('lookup.json unavailable:', err.message || err);
    setStatus('error');
    renderFooter();
  }
}

// --- footer ---
/** A date as "22 Oct 2026, 04:17 UTC" in the current language; '?' if invalid. */
export function formatWhen(date) {
  if (Number.isNaN(date.getTime())) return '?';
  const text = new Intl.DateTimeFormat(lang() === 'es' ? 'es-ES' : 'en-GB', {
    timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(date);
  return `${text} UTC`;
}

function renderFooter() {
  const counts = $('foot-counts');
  const month = $('dbip-month');
  if (status !== 'ready') {
    counts.textContent = t(status === 'error' ? 'foot_unavailable' : 'foot_loading');
    month.textContent = '';
    return;
  }
  const vars = {
    v4: formatCount(index.counts.v4, lang()),
    v6: formatCount(index.counts.v6, lang()),
    when: formatWhen(index.generatedAt),
    s: index.sourcesWithData,
  };
  counts.textContent = t(index.ipv6Published ? 'foot_counts' : 'foot_counts_no_v6', vars);
  month.textContent = index.dbipMonth ? ` ${t('dbip_month', { month: index.dbipMonth })}` : '';
}

// --- ticker: one random listed entry every ~1.5 s ---
const TICK_MS = 1500;
const TICK_LINES = 6;
let tickTimer = null;

function randomEntry() {
  const v6 = index.v6 && index.v6.full.items;
  const v4 = index.v4.full.items;
  const pool = v6 && v6.length && Math.random() < 0.08 ? v6 : v4;
  if (!pool.length) return null;
  const [cidr, sources, cc] = pool[Math.floor(Math.random() * pool.length)];
  const src = index.sources[(sources || [])[0]];
  return { cidr, cc: cc || '', src };
}

function tickerLine() {
  const entry = randomEntry();
  if (!entry) return null;
  const li = document.createElement('li');
  const ip = document.createElement('span');
  ip.className = 'tk-ip';
  ip.textContent = `▲ ${maskCidr(entry.cidr)}`;
  const parts = [countryText(countryKind(entry.cc, index.dbipMonth), entry.cc)].filter(Boolean);
  if (entry.src) parts.push(entry.src.name, categoryName(entry.src.category));
  const rest = document.createElement('span');
  rest.textContent = ` · ${parts.join(' · ')}`;
  li.append(ip, rest);
  return li;
}

function tickerActive() {
  return index && !map.reduced && window.innerWidth >= NARROW && !document.hidden;
}

function tick() {
  if (!tickerActive()) return;
  const list = $('ticker-list');
  const li = tickerLine();
  if (!li) return;
  list.prepend(li);
  while (list.children.length > TICK_LINES) list.lastElementChild.remove();
}

function startTicker() {
  if (tickTimer || !index) return;
  tick();
  tickTimer = setInterval(tick, TICK_MS); // ticks are skipped while hidden: no pile-up
}

// --- language toggle ---
function renderLangToggle() {
  for (const b of document.querySelectorAll('.lang button')) {
    b.setAttribute('aria-pressed', String(b.dataset.lang === lang()));
  }
}

document.querySelector('.lang').addEventListener('click', (event) => {
  const b = event.target.closest('button[data-lang]');
  if (b) setLang(b.dataset.lang);
});

document.addEventListener('langchange', () => {
  renderLangToggle();
  renderStatus();
  renderFooter();
  $('ticker-list').replaceChildren();
  tick();
});

// --- search box, examples, retry ---
// The first example (185.220.101.4 in the markup, until the data loads) becomes an address
// that is listed today.
function setExample() {
  const ip = exampleIp(index);
  const ex = document.querySelector('.ex');
  if (ip && ex) ex.textContent = ip;
}

els.form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (searchHandler) searchHandler(els.q.value);
});

for (const ex of document.querySelectorAll('.ex')) {
  ex.addEventListener('click', () => {
    els.q.value = ex.textContent;
    els.form.requestSubmit();
  });
}

els.retry.addEventListener('click', () => { if (status === 'error') load(); });

applyStrings();
renderLangToggle();
load();
