// The "sources" dialog: every source in lookup.json with its link, category, today's counts,
// license_note and notice (the Spamhaus copyright line). Spamhaus appears here only as the
// source of data.
import { formatCount } from './core.js';
import { index, ready } from './app.js';
import { t, lang, categoryName } from './i18n.js';

const dialog = document.getElementById('sources');
const body = document.getElementById('src-body');
const opener = document.getElementById('src-open');
let returnFocus = null;

function cell(row, content, className) {
  const td = document.createElement('td');
  if (className) td.className = className;
  if (content instanceof Node) td.append(content); else td.textContent = content;
  row.append(td);
  return td;
}

/** An external link (new tab) with a visible ↗ and a hidden "opens in a new tab". */
export function externalLink(href, text) {
  const a = document.createElement('a');
  a.href = href;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = text;
  const arrow = document.createElement('span');
  arrow.setAttribute('aria-hidden', 'true');
  arrow.textContent = ' ↗';
  const hint = document.createElement('span');
  hint.className = 'sr-only';
  hint.textContent = ` ${t('new_tab')}`;
  a.append(arrow, hint);
  return a;
}

/** A category badge ("attack", "C2"). */
export function badge(category) {
  const b = document.createElement('span');
  b.className = `badge cat-${category === 'c2' ? 'c2' : 'attack'}`;
  b.textContent = categoryName(category);
  return b;
}

const safeUrl = (url) => (/^https:\/\//i.test(url || '') ? url : null);

function render() {
  if (!index) {
    const row = document.createElement('tr');
    cell(row, t('sources_wait')).colSpan = 5;
    body.replaceChildren(row);
    return;
  }
  const rows = index.sources.map((src) => {
    const row = document.createElement('tr');
    const url = safeUrl(src.url);
    const name = url ? externalLink(url, src.name) : document.createTextNode(src.name);
    const nameCell = cell(row, name, 'src-name');
    if (!src.ok) {
      const failed = document.createElement('span');
      failed.className = 'src-failed';
      failed.textContent = ` · ${t('src_failed')}`;
      nameCell.append(failed);
    }
    cell(row, badge(src.category));
    cell(row, `${formatCount(src.entries || 0, lang())} · ${formatCount(src.entries6 || 0, lang())}`,
      'num');
    cell(row, src.license_note || '—');
    cell(row, src.notice || '—', 'notice');
    return row;
  });
  body.replaceChildren(...rows);
}

function open() {
  returnFocus = document.activeElement;
  render();
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
  dialog.querySelector('.dlg-close').focus();
}

function close() {
  if (typeof dialog.close === 'function') dialog.close();
  else dialog.removeAttribute('open');
}

opener.addEventListener('click', open);
dialog.querySelector('.dlg-close').addEventListener('click', close);
// a click on the backdrop (the dialog box itself, outside its content) closes it
dialog.addEventListener('click', (event) => { if (event.target === dialog) close(); });
dialog.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && typeof dialog.showModal !== 'function') close();
});
dialog.addEventListener('close', () => {
  if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
  returnFocus = null;
});
document.addEventListener('langchange', () => { if (dialog.open) render(); });
ready.then(() => { if (dialog.open) render(); });
