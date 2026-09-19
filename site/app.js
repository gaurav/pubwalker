// pubwalker site. No build step, no dependencies. One route:
//   /?doi=<doi>[&tab=backscatter|anatomy|comparison]
// shows the precomputed report from data/<slug>.json when the pipeline has produced one, otherwise a
// keyless live look-up (OpenAlex citers + Semantic Scholar contexts, no LLM). The tabs are the two
// approaches (how the paper is cited; what it argues) and the comparison that needs both.
const app = document.getElementById('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const WINDOW_LABEL = { 'last-12-months': 'Last 12 months', 'last-5-years': 'Last 5 years', 'all-time': 'All time' };
const fmt = (n) => (n ?? 0).toLocaleString();
// A stat tile for a dollar figure, dropped entirely for a report exported before per-report costs were tracked.
const money = (usd, label) => (usd == null ? '' : `<div><b>$${usd.toFixed(2)}</b><span>${label}</span></div>`);
// In order of direction: the paper itself, what it cites, what cites it, and the two directions compared.
const TABS = { anatomy: 'Anatomy', outgoing: 'Outgoing', backscatter: 'Backscatter', comparison: 'Claimed vs cited' };
const ROLES = ['uses-tool-or-method', 'uses-data', 'background-claim', 'compares-against', 'extends-or-modifies', 'critiques-or-contradicts', 'incidental'];
const INTRO = {
  backscatter: `<p class="small muted">How the literature uses this paper. Every citing passage we could retrieve was given a role
    (a tool run, data reused, a background claim, a comparison, an extension, a critique, or incidental), then synthesised per
    time window; each claim links to the citing papers it rests on.</p>`,
  anatomy: `<p class="small muted">The paper taken apart. The question it asks and what it concludes lead; below them, how it got
    there — the assumptions it borrows, its design, data, analysis, results, implications and stated limitations, each with the
    span of text it was read from.</p>`,
  outgoing: `<p class="small muted">The paper's own reference list, read the same way its citers are read: every reference was
    given a role from the passages that cite it (a tool run, data reused, a background claim, a comparison, an extension, a critique,
    or incidental), so what this paper leans on can be set against what others lean on it for.</p>`,
  comparison: `<p class="small muted">Does the literature use the paper for what it claims? The paper's own conclusions set against
    the roles its citers actually assign it.</p>`,
};
const UNAVAILABLE = '<p class="muted">Not available in live mode; run the pipeline for this paper.</p>';
const SOURCE_LABEL = { 'pmc-full-text': 'anatomy read from the full text', 'abstract-only': 'anatomy read from the abstract alone' };
// The role mix of the sampled citers as one stacked bar: the site's headline question, at a glance, in the report's own colours.
const roleStrip = (roles) => {
  const shown = ROLES.map((r) => [r, roles?.[r] || 0]).filter(([, n]) => n);
  return shown.length ? `<div class="strip">${shown.map(([r, n]) => `<i style="flex:${n};background:${roleColor(r)}" title="${esc(r)}: ${n}"></i>`).join('')}</div>` : '';
};
const roleLead = (roles) => {
  const shown = Object.entries(roles || {}).filter(([, n]) => n);
  if (!shown.length) return '';
  const [role, n] = shown.reduce((a, b) => (b[1] > a[1] ? b : a));
  return `${roleBadge(role)} for ${n} of ${shown.reduce((t, [, m]) => t + m, 0)} classified citers`;
};
// How varied the downstream use is: the effective number of roles, exp(Shannon entropy) of the role mix.
// 1 means every classified citer used the paper for the same thing, 7 means an even spread over all seven roles.
// It is what citation counts cannot say: SequenceMatrix is cited 2,685 times for one thing (1.1), ReMap 282 times for six (3.3).
// Which per-model tiles a report shows beside its total: a cheap model classifies passages and a strong one
// synthesises, and the split is the point of that division of labour. Nothing for a report exported before the
// split was recorded, and nothing when one model did the whole run, where a tile would just repeat the total.
// The models a report actually billed for a set of pipeline steps, for the note beneath it. Read from what was
// spent rather than hardcoded, so swapping a model in cannot leave the prose describing the old one. No vendor
// prefix: the point of reading it from data is that the model need not be a Claude one.
const modelsFor = (byStep, steps) => {
  const used = new Set();
  for (const step of steps) for (const m of Object.keys((byStep || {})[step] || {})) used.add(m);
  return [...used].sort().map((m) => m[0].toUpperCase() + m.slice(1)).join(' and ');
};
const costRows = (byModel) => {
  const rows = Object.entries(byModel || {}).filter(([, usd]) => usd > 0);
  return rows.length > 1 ? rows.sort((a, b) => b[1] - a[1]) : [];
};
const variety = (roles) => {
  const ns = Object.values(roles || {}).filter((n) => n > 0);
  const total = ns.reduce((a, b) => a + b, 0);
  return total ? Math.exp(-ns.reduce((h, n) => h + (n / total) * Math.log(n / total), 0)) : null;
};
const SORTS = {
  variety: ['role variety', (e) => -(variety(e.roles) ?? 0)],
  cost: ['LLM cost', (e) => -(e.cost_usd ?? 0)],
  citations: ['citations', (e) => -(e.cited_by_count ?? 0)],
  year: ['year', (e) => e.year ?? 0],
};
// The choice follows the reader to a report page, whose Examples list is sorted the same way. A browser that
// refuses localStorage (private mode, blocked site data) just gets the default back on every page.
const remembered = (value) => { try { return value === undefined ? localStorage.getItem('sort') : localStorage.setItem('sort', value); } catch { return null; } };
let sortKey = SORTS[remembered()] ? remembered() : 'variety';
const ordered = (index) => [...index].sort((a, b) => SORTS[sortKey][1](a) - SORTS[sortKey][1](b));

function setSort(key) {
  sortKey = key;
  remembered(key);
  fillExamples();
  home();
}

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
const INDEX = json('data/index.json').catch(() => []);  // precomputed reports; empty until the pipeline has run

// ---------- home ----------
async function home() {
  const index = await INDEX;
  app.innerHTML = `
    <h1>What is this paper used for?</h1>
    <p>Two questions about any paper, answered from the papers that cite it and from its own text:
    <b>what role does it play in the literature</b> (a tool people run, a finding people build on, a name in a list), and
    <b>what does its argument rest on</b>. Reports below were produced by the <a href="https://github.com/gaurav/pubwalker" target="_blank" rel="noopener">pipeline</a>
    with a cheap model classifying each citing passage and a stronger one synthesising; every claim links to its evidence.</p>
    <div class="rowhead"><h2>Reports</h2>
      ${index.length > 1 ? `<label class="small muted">Sort by <select class="jump" onchange="setSort(this.value)">${Object.entries(SORTS).map(([k, [label]]) =>
        `<option value="${k}"${k === sortKey ? ' selected' : ''}>${label}</option>`).join('')}</select></label>` : ''}</div>
    ${index.some((e) => e.cost_usd != null) ? `<p class="small muted">${index.length} reports, $${index.reduce((t, e) => t + (e.cost_usd || 0), 0).toFixed(2)} of LLM calls to produce all of them.</p>` : ''}
    ${index.some((e) => e.roles) ? `<p class="small muted">The bar on each report is the role mix of its sampled citers: ${ROLES.map(roleBadge).join(' ')}</p>` : ''}
    ${index.length ? ordered(index).map((e) => `
      <div class="card">
        <a class="title" href="?doi=${encodeURIComponent(e.doi)}">${esc(e.title)}</a>
        <div class="muted small">${esc(e.venue || '')} ${esc(e.year || '')} · doi:${esc(e.doi)}</div>
        <div class="nums">
          <div><b>${fmt(e.cited_by_count)}</b><span>citations (OpenAlex)</span></div>
          ${Object.entries(e.windows || {}).map(([w, n]) => `<div><b>${fmt(n)}</b><span>${esc(WINDOW_LABEL[w] || w)}</span></div>`).join('')}
          ${money(e.cost_usd, 'LLM cost')}
          ${variety(e.roles) ? `<div><b>${variety(e.roles).toFixed(1)}</b><span>role variety (of 7)</span></div>` : ''}
        </div>
        ${roleStrip(e.roles)}
        <div class="muted small">${[roleLead(e.roles), SOURCE_LABEL[e.source], e.outgoing && `${e.outgoing} of its own references classified`].filter(Boolean).join(' · ')}</div>
      </div>`).join('') : '<p class="muted">No precomputed reports yet.</p>'}
    <h2>Try any DOI</h2>
    <p class="small muted">Shows the precomputed report if the pipeline has produced one. Otherwise a live look-up in your browser, no LLM:
    citing works from OpenAlex and citation sentences from Semantic Scholar, whose coarse "intents" stand in for the role classification.</p>
    <form class="live">
      <input name="doi" placeholder="10.1126/science.1225829" required>
      <button>Look up</button>
    </form>`;
}

// ---------- shared pieces ----------
// Horizontal bars, largest first; categories with no hits are listed below the chart instead of drawn as empty rows.
const bars = (counts, colorFn, none = 'No sampled citers used it for') => {
  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  const shown = entries.filter(([, n]) => n > 0), empty = entries.filter(([, n]) => !(n > 0)).map(([k]) => k);
  const max = Math.max(1, ...shown.map(([, n]) => n));
  return `<div class="bars">${shown.map(([k, n]) => `
    <span>${esc(k)}</span><div><div class="bar" style="width:${(100 * n / max).toFixed(1)}%;${colorFn ? 'background:' + colorFn(k) : ''}"></div></div><span class="n">${fmt(n)}</span>`).join('')}</div>
    ${empty.length ? `<p class="small muted">${none}: ${empty.map(esc).join(', ')}.</p>` : ''}`;
};
const roleColor = (r) => `var(--r-${r})`;
const roleBadge = (r) => r ? `<span class="role" style="background:${roleColor(r)}">${esc(r)}</span>` : '';

const yearChart = (years) => {
  if (!years?.length) return '';
  const by = Object.fromEntries(years), lo = years[0][0], hi = years[years.length - 1][0];
  years = Array.from({ length: hi - lo + 1 }, (_, i) => [lo + i, by[lo + i] || 0]);  // fill empty years so the axis stays linear
  const max = Math.max(...years.map(([, n]) => n));
  return `<div class="years">${years.map(([y, n]) => `<div style="height:${(100 * n / max).toFixed(1)}%" data-l="${y}: ${n}"></div>`).join('')}</div>
    <div class="yl"><span>${years[0][0]}</span><span>${years[years.length - 1][0]}</span></div>`;
};

const links = (c) => [
  c.doi && `<a href="https://doi.org/${esc(c.doi)}">doi</a>`,
  c.pmid && `<a href="https://pubmed.ncbi.nlm.nih.gov/${esc(c.pmid)}/">pubmed</a>`,
  c.pmcid && `<a href="https://europepmc.org/article/PMC/${esc(c.pmcid)}">full text</a>`,
  c.id && `<a href="https://openalex.org/${esc(c.id)}">openalex</a>`,
].filter(Boolean).join(' · ');

const citerDetails = (c, open = false) => `
  <details id="c-${esc(c.id)}" ${open ? 'open' : ''}>
    <summary>${roleBadge(c.role?.role)} <b>${esc(c.title)}</b> <span class="muted">${[c.year, c.venue || c.type].filter(Boolean).map(esc).join(', ')}</span></summary>
    <div class="small muted">${links(c)}${c.role ? ` · stance: ${esc(c.role.stance)} · confidence: ${esc(c.role.confidence)}` : ''}</div>
    ${c.role ? `<p><b>Used for:</b> ${esc(c.role.what_for)}${c.role.combined_with?.length ? ` <span class="muted">· with ${esc(c.role.combined_with.join(', '))}</span>` : ''}</p>` : ''}
    ${(c.passages || []).map((p) => `<div class="pass"><div class="src">${p.source === 'epmc' ? 'Europe PMC full text' : 'Semantic Scholar context'}${p.section ? ` · ${esc(p.section)}` : ''}</div>${esc(p.text)}</div>`).join('')}
  </details>`;

const emph = (text) => esc(text).replace(/\*\*(.+?)\*\*/, '<b>$1</b>');  // the model marks each item's key phrase with **…**
// Anatomy's two halves. The Question frames what the paper is for and the Conclusions say what it found, so the two
// lead the tab in a lede of their own; every other section is how the paper got from one to the other, and only those
// sections reach the floating TOC, the highlight toggle and the kind filter. Numbering is untouched by the split, so
// C1 still means the first conclusion and a conclusion's "rests on" chips still land on R2 down in the body.
const anatomySections = (S) => {
  const LETTERS = [['conclusions', 'C'], ['assumptions', 'A'], ['design', 'D'], ['data', 'T'], ['analysis', 'N'], ['results', 'R'], ['implications', 'I'], ['limitations', 'L']];
  const present = LETTERS.filter(([k]) => S && S[k] && S[k].length);
  return { lede: present.filter(([k]) => k === 'conclusions'), body: present.filter(([k]) => k !== 'conclusions') };
};
// A conclusion's `based_on` ids number the results list from 1, so R2 is results[1]. Resolving them here lets the link
// out of a conclusion say what it points at rather than just "R2"; the **…** key-phrase markers come off for the tooltip.
const resultText = (S) => {
  const out = {};
  ((S && S.results) || []).forEach((r, i) => { out[`R${i + 1}`] = String((r && r.text) || '').replace(/\*\*/g, ''); });
  return out;
};
const claims = (s, citers) => s ? `
  <ol class="claims">${s.claims.map((cl) => `<li class="${cl.highlight ? 'hi' : ''}">${emph(cl.text)} ${cl.cites.map((id) => `<a class="chip" href="#c-${esc(id)}" title="${esc(citers[id]?.title || id)}" onclick="show('c-${esc(id)}')">${esc(id)}</a>`).join('')}</li>`).join('')}</ol>
  ${s.follow_ups?.length ? `<h3>Follow-up questions</h3><ul>${s.follow_ups.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}` : '<p class="muted">Not synthesised.</p>';

window.show = (elId) => { const d = document.getElementById(elId); if (d) { d.open = true; d.scrollIntoView({ block: 'center' }); } };  // open a <details> and scroll to it

// ---------- outgoing: what the paper uses its own references for ----------
// A reference's section path is folded to the IMRaD part it sits in, so roles can be laid out by where they appear.
const imrad = (path) => {
  const s = (path || '').split(' > ')[0].toLowerCase();
  return !path ? 'No section' : /intro|background/.test(s) ? 'Introduction' : /method|material|procedure|experimental/.test(s) ? 'Methods'
    : /result/.test(s) ? 'Results' : /discussion|conclusion/.test(s) ? 'Discussion' : 'Other';
};
const IMRAD = ['Introduction', 'Methods', 'Results', 'Discussion', 'Other', 'No section'];
const median = (xs) => { const s = xs.filter((x) => x != null).sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
const shortRef = (r) => r.title || r.text.slice(0, 120);

function outgoingPanel(d, index) {
  const O = d.outgoing;
  if (!O) return '<p class="muted">Not extracted.</p>';
  const a = d.anchor, refs = O.references, cited = refs.filter((r) => r.mentions.length), classified = refs.filter((r) => r.role);
  const mentions = refs.reduce((n, r) => n + r.mentions.length, 0);
  const ages = refs.map((r) => (r.year && a.year ? a.year - r.year : null)).filter((x) => x != null && x >= 0);
  const years = refs.map((r) => r.year).filter(Boolean);
  const reports = Object.fromEntries((index || []).map((e) => [e.doi, e]));
  const top = (h) => Object.entries(h).sort((x, y) => y[1] - x[1])[0];
  const outTop = top(O.roles), inRoles = d.windows?.['all-time']?.roles || {}, inTop = top(inRoles);
  // Section × role: how many mentions of each role fall in each part of the paper.
  const cell = {};
  for (const r of classified) for (const m of r.mentions) cell[`${imrad(m.section)}|${r.role.role}`] = (cell[`${imrad(m.section)}|${r.role.role}`] || 0) + 1;
  const used = ROLES.filter((k) => O.roles[k]), secs = IMRAD.filter((s) => used.some((k) => cell[`${s}|${k}`]));
  const maxCell = Math.max(1, ...Object.values(cell));
  const perYear = {};
  for (const y of years) perYear[y] = (perYear[y] || 0) + 1;
  const roleYears = used.map((k) => [k, median(refs.filter((r) => r.role?.role === k).map((r) => r.year))]).filter(([, y]) => y);
  const assumptions = (d.structure?.assumptions || []).map((s, i) => [`A${i + 1}`, s.sources || []]);
  const grounds = (r) => assumptions.filter(([, src]) => src.includes(r.id)).map(([id]) => `<a class="chip" href="#${id}" onclick="showTab('anatomy')">${id}</a>`).join('');
  const weight = (r) => [r.mentions.length, new Set(r.mentions.map((m) => m.section)).size];
  const bearing = [...cited].sort((x, y) => weight(y)[0] - weight(x)[0] || weight(y)[1] - weight(x)[1]).slice(0, 10);
  const refDetails = (r) => `
    <details class="ref" id="r-${esc(r.id)}" data-role="${esc(r.role?.role || '')}">
      <summary>${roleBadge(r.role?.role)} <b>${esc(shortRef(r))}</b> <span class="muted">${[r.year, r.mentions.length ? `${r.mentions.length} mention${r.mentions.length > 1 ? 's' : ''}` : 'not cited in the text'].filter(Boolean).map(esc).join(' · ')}</span></summary>
      <div class="small muted">${esc(r.id)} · ${links({ doi: r.doi, pmid: r.pmid, id: r.openalex_id })}${r.cited_by_count != null ? ` · ${fmt(r.cited_by_count)} citations` : ''}${r.doi && reports[r.doi] ? ` · <a href="?doi=${encodeURIComponent(r.doi)}">pubwalker report</a>` : ''}${r.role ? ` · stance: ${esc(r.role.stance)} · confidence: ${esc(r.role.confidence)}` : ''}</div>
      ${!r.title ? `<p class="small">${esc(r.text)}</p>` : ''}
      ${r.role ? `<p><b>Used for:</b> ${esc(r.role.what_for)}${grounds(r) ? ` <span class="small muted">grounds</span> ${grounds(r)}` : ''}</p>` : ''}
      ${r.mentions.map((m) => `<div class="pass"><div class="src">${esc(m.section || 'no section')}</div>${esc(m.text)}</div>`).join('')}
    </details>`;
  return `
    <div class="struct">
      <nav class="toc"><ul>
        <li><a href="#og-roles">Roles out vs in</a></li><li><a href="#og-where">Where in the paper</a></li><li><a href="#og-age">Reference age</a></li>
        <li><a href="#og-bearing">Load-bearing references</a></li><li><a href="#og-all">All references</a> <span class="muted">${refs.length}</span></li>
      </ul>
      <h4>Show only</h4>
      <div class="rf">${used.map((k) => `<label><input type="checkbox" id="or-${k}"> ${roleBadge(k)} <span class="muted">${O.roles[k]}</span></label>`).join('')}</div>
      </nav>
      <div class="body">
      <div class="nums">
        <div><b>${fmt(refs.length)}</b><span>references</span></div>
        <div><b>${fmt(cited.length)}</b><span>cited in the text</span></div>
        <div><b>${fmt(mentions)}</b><span>mentions</span></div>
        ${ages.length ? `<div><b>${median(ages)} yr</b><span>median age when published</span></div>` : ''}
        ${years.length ? `<div><b>${Math.min(...years)}</b><span>oldest reference</span></div>` : ''}
      </div>
      <h3 id="og-roles">Roles out vs roles in</h3>
      <div class="twin">
        <div><h4>What this paper uses its ${fmt(classified.length)} references for</h4>${bars(O.roles, roleColor, 'Never used for')}</div>
        <div><h4>What ${fmt(Object.values(inRoles).reduce((x, y) => x + y, 0))} sampled citers use it for (all time)</h4>${Object.keys(inRoles).length ? bars(inRoles, roleColor) : '<p class="muted">No sample.</p>'}</div>
      </div>
      ${outTop && inTop ? `<p class="small muted">It cites others mostly as <b>${esc(outTop[0])}</b>${inTop[0] === outTop[0] ? ' and is cited the same way' : `, and is cited mostly as <b>${esc(inTop[0])}</b>`}.</p>` : ''}
      <h3 id="og-where">Where in the paper each role appears</h3>
      <table class="matrix"><tr><th></th>${used.map((k) => `<th>${roleBadge(k)}</th>`).join('')}<th>all</th></tr>
        ${secs.map((s) => `<tr><th>${s}</th>${used.map((k) => { const n = cell[`${s}|${k}`] || 0; return `<td${n ? ` style="background:color-mix(in srgb, ${roleColor(k)} ${Math.round(12 + 55 * n / maxCell)}%, transparent)"` : ''}>${n || ''}</td>`; }).join('')}<td>${used.reduce((t, k) => t + (cell[`${s}|${k}`] || 0), 0)}</td></tr>`).join('')}
      </table>
      <p class="small muted">Mentions of each role by the part of the paper they fall in.</p>
      <h3 id="og-age">Reference age</h3>
      ${yearChart(Object.entries(perYear).map(([y, n]) => [+y, n]).sort((x, y) => x[0] - y[0]))}
      ${roleYears.length ? `<p class="small muted">Median reference year by role: ${roleYears.map(([k, y]) => `${roleBadge(k)} ${y}`).join(' ')}.</p>` : ''}
      <h3 id="og-bearing">Load-bearing references</h3>
      <p class="small muted">Cited most often, in the most sections; "grounds" links to the assumptions in Anatomy that name the reference.</p>
      <table>${bearing.map((r) => `<tr><td>${roleBadge(r.role?.role)}</td><td><a href="#r-${esc(r.id)}" onclick="show('r-${esc(r.id)}')">${esc(shortRef(r))}</a> <span class="muted small">${esc(r.year || '')}</span></td>
        <td class="small muted">${r.mentions.length}× in ${weight(r)[1]} section${weight(r)[1] > 1 ? 's' : ''}</td><td class="small muted">${r.cited_by_count != null ? fmt(r.cited_by_count) + ' cites' : ''}</td><td>${grounds(r)}</td></tr>`).join('')}</table>
      <h3 id="og-all">All references, by role</h3>
      ${used.map((k) => `<h4>${roleBadge(k)} <span class="muted">${O.roles[k]}</span></h4>${classified.filter((r) => r.role.role === k).map(refDetails).join('')}`).join('')}
      ${refs.some((r) => !r.role) ? `<h4>Not located in the text <span class="muted">${refs.filter((r) => !r.role).length}</span></h4>${refs.filter((r) => !r.role).map(refDetails).join('')}` : ''}
      </div>
    </div>`;
}

// ---------- paper page: shared header + one tab per approach ----------
// report() and live() each return { anchor, nums, years, panels: {tab: html}, note, after() } and paper() lays them out.
async function paper(doi, tab) {
  document.title = `pubwalker: ${doi}`;
  app.innerHTML = `<p class="small"><a href=".">← home</a></p><p class="muted">Loading ${esc(doi)}…</p>`;
  const slug = doi.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');  // same as slugify() in the pipeline
  let d = null;
  try { d = await json(`data/${slug}.json`); } catch { /* ponytail: no report means live mode, at the cost of one 404 in the console */ }
  let page;
  try { page = d ? report(d, await INDEX) : await live(doi); } catch (e) {
    app.innerHTML += `<p class="flash">Lookup failed: ${esc(e.message)}. Check the DOI, or try again if a rate limit was hit.</p>`;
    return;
  }
  if (!TABS[tab]) tab = Object.keys(TABS)[0];
  const a = page.anchor;
  document.title = `pubwalker: ${a.title}`;
  app.innerHTML = `
    <p class="small"><a href=".">← home</a></p>
    <h1>${esc(a.title)}</h1>
    <div class="muted">${esc(a.venue || '')} ${esc(a.year || '')} · ${links(a)} ·
      <button class="chip" onclick="navigator.clipboard.writeText(location.href).then(() => { this.textContent = 'copied'; })">copy link</button></div>
    <div class="nums">${page.nums}</div>
    ${yearChart(page.years)}
    <div class="tabs top">${Object.entries(TABS).map(([k, label]) => `<button data-t="${k}" class="${k === tab ? 'on' : ''}">${label}</button>`).join('')}</div>
    ${Object.keys(TABS).map((k) => `<section data-t="${k}" ${k === tab ? '' : 'hidden'}>${page.panels[k]}</section>`).join('')}
    <p class="small muted">${page.note}</p>`;
  window.showTab = (t) => {  // also called by cross-tab links, e.g. Outgoing's "grounds A3" chips into Anatomy
    app.querySelectorAll('.tabs.top button').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
    app.querySelectorAll('section[data-t]').forEach((s) => { s.hidden = s.dataset.t !== t; });
    history.replaceState(null, '', '?' + new URLSearchParams({ doi, tab: t }));
  };
  app.querySelector('.tabs.top').addEventListener('click', (e) => { if (e.target.dataset.t) showTab(e.target.dataset.t); });
  page.after?.();
}

// ---------- precomputed report ----------
function report(d, index) {
  const a = d.anchor, C = d.citers, wins = Object.keys(d.windows), first = wins[wins.length - 1];
  const windowPanel = (w) => {
    const W = d.windows[w];
    const sampled = W.sampled.map((id) => C[id]).filter(Boolean);
    return `
      <div class="nums">
        <div><b>${fmt(W.total)}</b><span>citing works</span></div>
        <div><b>${fmt(W.with_passages)}</b><span>with a retrievable passage</span></div>
        <div><b>${fmt(sampled.length)}</b><span>sampled and classified</span></div>
      </div>
      <h3 id="bs-roles">What the sampled citers use it for</h3>
      ${bars(W.roles, roleColor)}
      <h3 id="bs-synthesis">Synthesis</h3>
      ${claims(W.synthesis, C)}
      <h3 id="bs-evidence">Evidence: the ${sampled.length} sampled citing papers</h3>
      ${sampled.sort((x, y) => (y.year || 0) - (x.year || 0)).map((c) => citerDetails(c)).join('')}`;
  };
  const S = d.structure;
  const { lede, body } = anatomySections(S);
  const RESULT = resultText(S);
  const KINDS = { fact: ['◆', 'fact: established knowledge taken as given'], method: ['⚙', 'method: how something was done'], finding: ['▲', 'finding: observed or measured in this work'], claim: ['✦', 'claim: the authors’ interpretation, argument or proposal'], gap: ['○', 'gap: a caveat or something not addressed'] };
  const cap = (k) => k[0].toUpperCase() + k.slice(1);
  const structItem = (it, id) => `<li id="${id}" class="${it.highlight ? 'hi' : ''}" data-kind="${esc(it.kind || '')}">
      ${it.kind ? `<span class="k k-${it.kind}" title="${esc(KINDS[it.kind]?.[1] || it.kind)}">${KINDS[it.kind]?.[0] || '•'}</span>` : ''}<span class="n">${id}</span>
      ${emph(it.text)}${it.sources?.length ? ` <span class="muted small">[${it.sources.map((s) => `<abbr title="${esc(S.references?.[s] || s)}">${esc(s)}</abbr>`).join(', ')}]</span>` : ''}${it.based_on?.length ? ` <span class="small muted">rests on</span> ${it.based_on.map((r) => `<a class="chip" href="#${esc(r)}" title="${esc(RESULT[r] || r)}">${esc(r)}</a>`).join('')}` : ''}${it.evidence && it.evidence !== 'not stated' ? `<div class="ev">${it.section ? `<span class="sec">${a.pmcid ? `<a href="https://pmc.ncbi.nlm.nih.gov/articles/${esc(a.pmcid)}/">${esc(it.section)}</a>` : esc(it.section)}</span> ` : ''}“${esc(it.evidence)}”</div>` : ''}</li>`;
  const structure = S ? `
    ${S.source === 'pmc-full-text' ? '<p class="small muted">Extracted from the PMC full text; each item carries the span it was read from.</p>' : `
    <div class="flash"><b>No full text was available for this paper.</b> Everything below was extracted from the title and abstract alone,
    so design, data, analysis and limitations are thin or guessed, and no assumption can be tied to a cited reference. Treat this tab as a sketch.
    ${S.abstract ? `<p><b>The abstract, in full, as the model saw it:</b></p><p>${esc(S.abstract)}</p>` : ''}</div>`}
    <div class="struct">
      <div class="lede" id="s-lede">
        <h2>Question</h2>
        <p class="q">${esc(S.question)}</p>
        ${lede.map(([k, L]) => `<h2 id="s-${k}">${cap(k)}</h2>
        <p class="small muted">What the authors say the results show. Each links to the results it rests on, below.</p>
        <ul class="items lede-items">${S[k].map((it, i) => structItem(it, `${L}${i + 1}`)).join('')}</ul>`).join('')}
      </div>
      <nav class="toc">
        <p class="small back"><a href="#s-lede">↑ Question &amp; conclusions</a></p>
        <h4>How it got there</h4>
        <ul>${body.map(([k]) => `<li><a href="#s-${k}">${cap(k)}</a> <span class="muted">${S[k].length}</span></li>`).join('')}</ul>
        <label><input type="checkbox" id="hi-only"> highlights only</label>
        <label><input type="checkbox" id="ev-on"> show evidence spans</label>
        <h4>Kinds of statement</h4>
        <div class="legend">${Object.entries(KINDS).map(([k, [g, t]]) => [k, g, t, body.reduce((n, [s]) => n + S[s].filter((it) => it.kind === k).length, 0)]).filter(([, , , n]) => n).sort((a, b) => b[3] - a[3])
          .map(([k, g, t, n]) => `<label class="k k-${k}" title="${esc(t)}"><input type="checkbox" id="kind-${k}"> ${g} ${k} <span class="muted">${n}</span></label>`).join('')}</div>
      </nav>
      <div class="body">
      ${body.map(([k, L]) => `<section id="s-${k}"><h3>${cap(k)}</h3><ul class="items">${S[k].map((it, i) => structItem(it, `${L}${i + 1}`)).join('')}</ul></section>`).join('')}
      </div>
    </div>` : '<p class="muted">Not extracted.</p>';
  const KIND = { 'cited-as-claimed': ['a', 'Cited as claimed'], 'cited-for-something-else': ['b', 'Cited for something else'], 'claimed-but-not-cited': ['c', 'Claimed but not cited'] };
  const comparison = d.comparison ? `<ul>${d.comparison.points.map((p) => `<li><span class="kind ${KIND[p.kind]?.[0]}">${esc(KIND[p.kind]?.[1] || p.kind)}</span>${esc(p.text)}</li>`).join('')}</ul>` : '<p class="muted">Not compared.</p>';

  return {
    anchor: a,
    years: d.years,
    nums: `<div><b>${fmt(a.cited_by_count)}</b><span>citations in OpenAlex</span></div><div><b>${esc(d.generated)}</b><span>report generated</span></div>${money(d.cost_usd, 'LLM cost for this report')}${costRows(d.cost_by_model).map(([m, usd]) => money(usd, `of that on ${esc(m[0].toUpperCase() + m.slice(1))}`)).join('')}`,
    panels: {
      backscatter: `${INTRO.backscatter}
        <div class="struct">
        <nav class="toc"><ul>
          <li><a href="#bs-overall">Overall</a></li>
          <li><a href="#bs-window">By time window</a>
            <ul><li><a href="#bs-roles">Roles</a></li><li><a href="#bs-synthesis">Synthesis</a></li><li><a href="#bs-evidence">Evidence</a></li></ul></li>
        </ul>
        <label><input type="checkbox" id="bs-hi"> highlights only</label></nav>
        <div class="body">
        <h2 id="bs-overall">Overall</h2>
        ${claims(d.overall, C)}
        <h2 id="bs-window">By time window</h2>
        <div class="tabs win">${wins.map((w) => `<button data-w="${esc(w)}" class="${w === first ? 'on' : ''}">${esc(WINDOW_LABEL[w] || w)}</button>`).join('')}</div>
        <div id="win">${windowPanel(first)}</div>
        </div></div>`,
      anatomy: INTRO.anatomy + structure,
      outgoing: INTRO.outgoing + outgoingPanel(d, index),
      comparison: INTRO.comparison + comparison,
    },
    note: `Roles were assigned per passage by ${esc(modelsFor(d.cost_by_step, ['roles', 'outgoing']) || 'a cheap model')} from Europe PMC full-text paragraphs (with section) or Semantic Scholar citation sentences; syntheses and the argument structure by ${esc(modelsFor(d.cost_by_step, ['synth', 'structure']) || 'a stronger model')}. Samples are seeded random draws from citers with a retrievable passage, so paywalled citers are under-represented.`,
    after() {
      app.querySelector('.tabs.win').addEventListener('click', (e) => {
        const w = e.target.dataset.w; if (!w) return;
        app.querySelectorAll('.tabs.win button').forEach((b) => b.classList.toggle('on', b.dataset.w === w));
        document.getElementById('win').innerHTML = windowPanel(w);
      });
    },
  };
}

// ---------- live mode ----------
async function live(doi) {
  const oa = (path, params) => json(`https://api.openalex.org${path}?${new URLSearchParams({ mailto: 'pubwalker@example.org', ...params })}`);
  const w = await oa(`/works/https://doi.org/${doi}`, { select: 'id,doi,ids,title,publication_year,cited_by_count,primary_location' });
  const id = w.id.split('/').pop();
  const today = new Date(), iso = (d) => d.toISOString().slice(0, 10);
  const since = (days) => iso(new Date(today - days * 864e5));
  const [y1, y5, byYear] = await Promise.all([
    oa('/works', { filter: `cites:${id},from_publication_date:${since(365)}`, 'per-page': 1 }),
    oa('/works', { filter: `cites:${id},from_publication_date:${since(5 * 365 + 1)}`, 'per-page': 1 }),
    oa('/works', { filter: `cites:${id}`, group_by: 'publication_year' }),  // per-page would also cap the groups
  ]);
  const years = byYear.group_by.map((g) => [+g.key, g.count]).filter(([y]) => y > 1900).sort((a, b) => a[0] - b[0]);
  const anchor = { id, doi: (w.doi || '').replace('https://doi.org/', ''), pmid: w.ids?.pmid?.split('/').pop(), title: w.title, year: w.publication_year, venue: w.primary_location?.source?.display_name, cited_by_count: w.cited_by_count };
  return {
    anchor,
    years,
    nums: `<div><b>${fmt(w.cited_by_count)}</b><span>citations (OpenAlex)</span></div><div><b>${fmt(y1.meta.count)}</b><span>last 12 months</span></div><div><b>${fmt(y5.meta.count)}</b><span>last 5 years</span></div>`,
    panels: {
      backscatter: `${INTRO.backscatter}<h2>Citation sentences from Semantic Scholar</h2><div id="s2" class="muted">Fetching…</div>`,
      anatomy: INTRO.anatomy + UNAVAILABLE,
      outgoing: INTRO.outgoing + UNAVAILABLE,
      comparison: INTRO.comparison + UNAVAILABLE,
    },
    note: "Live mode stops here. The pipeline adds: Europe PMC full-text paragraphs with their section, a role for every passage, per-window syntheses with linked evidence, and the paper's argument structure.",
    async after() {
      const s2 = document.getElementById('s2');
      try {
        let data = [], offset = 0;
        while (offset != null && offset < 3000) {
          const r = await fetch(`https://api.semanticscholar.org/graph/v1/paper/DOI:${doi}/citations?fields=contexts,intents,title,year,externalIds&limit=1000&offset=${offset}`);
          if (r.status === 429) { s2.innerHTML = `<p>Semantic Scholar rate limit hit after ${data.length} citers; try again in a minute.</p>`; break; }
          if (!r.ok) throw new Error(`Semantic Scholar ${r.status}`);
          const page = await r.json();
          data = data.concat(page.data || []);
          offset = page.next ?? null;
          s2.textContent = `Fetched ${data.length} citers…`;
        }
        const withCtx = data.filter((c) => c.contexts?.length).sort((a, b) => (b.citingPaper.year || 0) - (a.citingPaper.year || 0));
        const intents = {};
        for (const c of data) for (const i of (c.intents?.length ? c.intents : ['(none given)'])) intents[i] = (intents[i] || 0) + 1;
        s2.className = '';
        s2.innerHTML = `
          <div class="nums"><div><b>${fmt(data.length)}</b><span>citers known to Semantic Scholar</span></div><div><b>${fmt(withCtx.length)}</b><span>with a citation sentence</span></div></div>
          <h3>Semantic Scholar's coarse intents</h3>${bars(intents)}
          <h3>Passages (newest first, up to 60)</h3>
          ${withCtx.slice(0, 60).map((c) => citerDetails({ id: c.citingPaper.paperId, title: c.citingPaper.title, year: c.citingPaper.year, doi: c.citingPaper.externalIds?.DOI, pmid: c.citingPaper.externalIds?.PubMed, passages: c.contexts.map((t) => ({ source: 's2', text: t })) })).join('')}`;
      } catch (e) {
        s2.innerHTML = `<p class="flash">Semantic Scholar lookup failed: ${esc(e.message)}. Try again if a rate limit was hit.</p>`;
      }
    },
  };
}

// ---------- route ----------
const q = new URLSearchParams(location.search);
const doi = (q.get('doi') || '').trim().replace(/^https?:\/\/doi\.org\//, '');
// Header: the "Examples" select lists the precomputed reports in the same order the home page shows them,
// the box takes any DOI for a live look-up.
// ponytail: a plain <select> is fine while there are a few dozen reports; a searchable picker if it grows past that.
async function fillExamples() {
  const sel = document.getElementById('examples');
  sel.length = 1;  // keep the "Examples" placeholder, replace the rest
  sel.insertAdjacentHTML('beforeend', ordered(await INDEX).map((e) => `<option value="${esc(e.doi)}">${esc(e.title)}</option>`).join(''));
}
fillExamples();
doi ? paper(doi, q.get('tab')) : home();
