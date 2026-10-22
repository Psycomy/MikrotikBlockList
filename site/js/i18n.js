// All UI strings, Spanish and English, and the helpers that apply them. Elements carry
// data-i18n="key" (textContent) or data-i18n-attr="attr:key;attr:key" (attributes).

const STRINGS = {
  es: {
    page_title: 'MikroBlockList · ¿Está esta IP en la lista?',
    tagline: 'threat blocklist · RouterOS v7',
    q_label: 'Dirección IP o rango CIDR',
    q_placeholder: 'Escribe una IP o un rango…',
    search: 'Buscar',
    help: 'Comprueba si una dirección IPv4 o IPv6, o un rango CIDR, está en la lista de bloqueo, en qué variantes (full, lite) y qué fuentes públicas la incluyen.',
    try: 'Prueba con',
    or: 'o',
    privacy: 'Tu búsqueda nunca sale de tu navegador.',
    loading: '> cargando lista…',
    ready: '> lista cargada · {n} entradas · {s} fuentes',
    unavailable: '> lista no disponible',
    retry: 'Reintentar',
    foot_counts: '{v4} IPv4 · {v6} IPv6 · actualizada {when} · {s} fuentes',
    foot_counts_no_v6: '{v4} IPv4 · IPv6 no publicada hoy · actualizada {when} · {s} fuentes',
    foot_loading: 'cargando datos de la lista…',
    foot_unavailable: 'datos de la lista no disponibles',
    dbip: 'IP Geolocation by DB-IP',
    dbip_month: '(datos de {month})',
    license: 'uso doméstico y no comercial',
    repo: 'código en GitHub',
    readme: 'README',
    ticker_label: 'En la lista ahora mismo',
    ticker_note: 'direcciones listadas, no tráfico en directo',
    lang_label: 'Idioma',
    several_countries: 'varios países',
    unknown_country: 'país desconocido',
    cat_attack: 'ataque',
    cat_c2: 'C2',
  },
  en: {
    page_title: 'MikroBlockList · Is this IP listed?',
    tagline: 'threat blocklist · RouterOS v7',
    q_label: 'IP address or CIDR range',
    q_placeholder: 'Type an IP or a range…',
    search: 'Search',
    help: 'Check whether an IPv4 or IPv6 address, or a CIDR range, is on the blocklist, in which variants (full, lite) and which public sources list it.',
    try: 'Try',
    or: 'or',
    privacy: 'Your search never leaves your browser.',
    loading: '> loading list…',
    ready: '> list loaded · {n} entries · {s} sources',
    unavailable: '> list unavailable',
    retry: 'Retry',
    foot_counts: '{v4} IPv4 · {v6} IPv6 · updated {when} · {s} sources',
    foot_counts_no_v6: '{v4} IPv4 · IPv6 not published today · updated {when} · {s} sources',
    foot_loading: 'loading list data…',
    foot_unavailable: 'list data unavailable',
    dbip: 'IP Geolocation by DB-IP',
    dbip_month: '({month} data)',
    license: 'home and non-commercial use',
    repo: 'code on GitHub',
    readme: 'README',
    ticker_label: 'On the list right now',
    ticker_note: 'listed addresses, not live traffic',
    lang_label: 'Language',
    several_countries: 'several countries',
    unknown_country: 'unknown country',
    cat_attack: 'attack',
    cat_c2: 'C2',
  },
};

const STORE_KEY = 'mbl-lang';
let current = initialLang();

function initialLang() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    if (saved === 'es' || saved === 'en') return saved;
  } catch { /* storage blocked: use the browser language */ }
  const langs = (typeof navigator !== 'undefined' && navigator.languages) || [];
  const first = String(langs[0] || (typeof navigator !== 'undefined' && navigator.language) || 'en');
  return first.toLowerCase().startsWith('es') ? 'es' : 'en';
}

/** The current language, 'es' or 'en'. */
export function lang() {
  return current;
}

/** The string for `key`, with {name} placeholders filled from `vars`; the key if unknown. */
export function t(key, vars) {
  const table = STRINGS[current];
  let text = key in table ? table[key] : (STRINGS.en[key] ?? key);
  if (vars) text = text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
  return text;
}

/** Fill every data-i18n / data-i18n-attr element under `root`. */
export function applyStrings(root = document) {
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of root.querySelectorAll('[data-i18n-attr]')) {
    for (const pair of el.dataset.i18nAttr.split(';')) {
      const [attr, key] = pair.split(':');
      if (attr && key) el.setAttribute(attr.trim(), t(key.trim()));
    }
  }
  document.documentElement.lang = current;
  document.title = t('page_title');
}

/** Switch language, re-apply the strings and fire a 'langchange' event on document. */
export function setLang(next) {
  if (next !== 'es' && next !== 'en') return;
  current = next;
  try { localStorage.setItem(STORE_KEY, next); } catch { /* not persisted */ }
  applyStrings();
  document.dispatchEvent(new CustomEvent('langchange', { detail: next }));
}

/** The regional-indicator flag emoji of an ISO alpha-2 code, or '' for anything else. */
export function flag(cc) {
  if (!/^[A-Za-z]{2}$/.test(cc || '')) return '';
  return String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1F1A5 + c.charCodeAt(0)));
}

const regionNames = {};
/** The country name of an ISO alpha-2 code in the current language; the code if unknown. */
export function countryName(cc) {
  if (!cc) return t('several_countries');
  try {
    regionNames[current] ||= new Intl.DisplayNames([current], { type: 'region' });
    return regionNames[current].of(cc.toUpperCase()) || cc;
  } catch {
    return cc;
  }
}

/** A source category ('attack', 'c2') in the current language. */
export function categoryName(category) {
  const key = `cat_${category}`;
  return key in STRINGS[current] ? t(key) : String(category || '');
}
