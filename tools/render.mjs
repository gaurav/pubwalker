// Render one paper page from site/app.js under a stub DOM and write the Anatomy panel's HTML, for checking
// the site without a browser: node tools/render.mjs <doi> <out.html>, run from the repo root.
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const doi = process.argv[2];
const els = {};
const el = (id) => (els[id] ??= { id, innerHTML: '', querySelector: () => el('x'), querySelectorAll: () => [], addEventListener() {}, insertAdjacentHTML() {}, classList: { toggle() {} } });
const g = {
  document: { getElementById: el, title: '' },
  window: {}, history: { replaceState() {} }, navigator: {},
  location: { search: `?doi=${encodeURIComponent(doi)}&tab=anatomy`, href: '' },
  fetch: async (url) => { const p = 'site/' + url.replace(/^\.?\//, ''); try { return { ok: true, status: 200, json: async () => JSON.parse(readFileSync(p, 'utf8')) }; } catch { return { ok: false, status: 404 }; } },
  URLSearchParams, console, setTimeout,
};
vm.createContext(g);
vm.runInContext(readFileSync('site/app.js', 'utf8'), g);
await new Promise((r) => setTimeout(r, 200));
const html = el('app').innerHTML;
const m = html.match(/<section data-t="anatomy"[^>]*>([\s\S]*?)<\/section>\s*<section data-t="comparison"/);
const out = m ? m[1] : html;
writeFileSync(process.argv[3], out);
console.log(`${out.length} chars written to ${process.argv[3]}`);
