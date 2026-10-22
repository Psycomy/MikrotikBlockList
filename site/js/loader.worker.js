// Module worker: fetch lookup.json, parse and index it off the main thread.
import { buildIndex } from './core.js';

self.onmessage = async (event) => {
  try {
    const response = await fetch(event.data.url, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = buildIndex(await response.json());
    self.postMessage({ index });
  } catch (err) {
    self.postMessage({ error: String((err && err.message) || err) });
  }
};
