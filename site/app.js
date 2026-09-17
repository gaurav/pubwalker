// pubwalker site. No build step, no dependencies. One route:
//   /?doi=<doi>[&tab=backscatter|anatomy|comparison]
// shows the precomputed report from data/<slug>.json when the pipeline has produced one, otherwise a
// keyless live look-up (OpenAlex citers + Semantic Scholar contexts, no LLM). The tabs are the two
// approaches (how the paper is cited; what it argues) and the comparison that needs both.
const app = document.getElementById('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const WINDOW_LABEL = { 'last-12-months': 'Last 12 months', 'last-5-years': 'Last 5 years', 'all-time': 'All time' };
const fmt = (n) => (n ?? 0).toLocaleString();
const TABS = { backscatter: 'Backscatter', anatomy: 'Anatomy', comparison: 'Claimed vs cited' };
const INTRO = {
  backscatter: `<p class="small muted">How the literature uses this paper. Every citing passage we could retrieve was given a role
    (a tool run, data reused, a background claim, a comparison, an extension, a critique, or incidental), then synthesised per
    time window; each claim links to the citing papers it rests on.</p>`,
  anatomy: `<p class="small muted">The paper taken apart: the question it asks, the assumptions it borrows, its
    design, data, analysis, results, conclusions, implications and stated limitations, each with the span of text it was read from.</p>`,
  comparison: `<p class="small muted">Does the literature use the paper for what it claims? The paper's own conclusions set against
    the roles its citers actually assign it.</p>`,
};
const UNAVAILABLE = '<p class="muted">Not available in live mode; run the pipeline for this paper.</p>';

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
    <b>what does its argument rest on</b>. Reports below were produced by the <a href="https://github.com/gaurav/pubwalker">pipeline</a>
    with a cheap model classifying each citing passage and a stronger one synthesising; every claim links to its evidence.</p>
    <h2>Reports</h2>
    ${index.length ? index.map((e) => `
      <div class="card">
        <a class="title" href="?doi=${encodeURIComponent(e.doi)}">${esc(e.title)}</a>
        <div class="muted small">${esc(e.venue || '')} ${esc(e.year || '')} · doi:${esc(e.doi)}</div>
        <div class="nums">
          <div><b>${fmt(e.cited_by_count)}</b><span>citations (OpenAlex)</span></div>
          ${Object.entries(e.windows || {}).map(([w, n]) => `<div><b>${fmt(n)}</b><span>${esc(WINDOW_LABEL[w] || w)}</span></div>`).join('')}
        </div>
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
const bars = (counts, colorFn) => {
  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  const shown = entries.filter(([, n]) => n > 0), empty = entries.filter(([, n]) => !(n > 0)).map(([k]) => k);
  const max = Math.max(1, ...shown.map(([, n]) => n));
  return `<div class="bars">${shown.map(([k, n]) => `
    <span>${esc(k)}</span><div><div class="bar" style="width:${(100 * n / max).toFixed(1)}%;${colorFn ? 'background:' + colorFn(k) : ''}"></div></div><span class="n">${fmt(n)}</span>`).join('')}</div>
    ${empty.length ? `<p class="small muted">No sampled citers used it for: ${empty.map(esc).join(', ')}.</p>` : ''}`;
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

const claims = (s, citers) => s ? `
  <ol class="claims">${s.claims.map((cl) => `<li>${esc(cl.text)} ${cl.cites.map((id) => `<a class="chip" href="#c-${esc(id)}" title="${esc(citers[id]?.title || id)}" onclick="show('${esc(id)}')">${esc(id)}</a>`).join('')}</li>`).join('')}</ol>
  ${s.follow_ups?.length ? `<h3>Follow-up questions</h3><ul>${s.follow_ups.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}` : '<p class="muted">Not synthesised.</p>';

window.show = (id) => { const d = document.getElementById(`c-${id}`); if (d) { d.open = true; d.scrollIntoView({ block: 'center' }); } };

// ---------- paper page: shared header + one tab per approach ----------
// report() and live() each return { anchor, nums, years, panels: {tab: html}, note, after() } and paper() lays them out.
async function paper(doi, tab) {
  document.title = `pubwalker: ${doi}`;
  app.innerHTML = `<p class="small"><a href=".">← home</a></p><p class="muted">Loading ${esc(doi)}…</p>`;
  const slug = doi.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');  // same as slugify() in the pipeline
  let d = null;
  try { d = await json(`data/${slug}.json`); } catch { /* ponytail: no report means live mode, at the cost of one 404 in the console */ }
  let page;
  try { page = d ? report(d) : await live(doi); } catch (e) {
    app.innerHTML += `<p class="flash">Lookup failed: ${esc(e.message)}. Check the DOI, or try again if a rate limit was hit.</p>`;
    return;
  }
  if (!TABS[tab]) tab = 'backscatter';
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
  app.querySelector('.tabs.top').addEventListener('click', (e) => {
    const t = e.target.dataset.t; if (!t) return;
    app.querySelectorAll('.tabs.top button').forEach((b) => b.classList.toggle('on', b.dataset.t === t));
    app.querySelectorAll('section[data-t]').forEach((s) => { s.hidden = s.dataset.t !== t; });
    history.replaceState(null, '', '?' + new URLSearchParams({ doi, tab: t }));
  });
  page.after?.();
}

// ---------- precomputed report ----------
function report(d) {
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
      <h3>What the sampled citers use it for</h3>
      ${bars(W.roles, roleColor)}
      <h3>Synthesis</h3>
      ${claims(W.synthesis, C)}
      <h3>Evidence: the ${sampled.length} sampled citing papers</h3>
      ${sampled.sort((x, y) => (y.year || 0) - (x.year || 0)).map((c) => citerDetails(c)).join('')}`;
  };
  const S = d.structure;
  // Conclusions sit right under the question: the two together are the paper in a glance. The rest is how it got there.
  const SECTIONS = [['conclusions', 'C'], ['assumptions', 'A'], ['design', 'D'], ['data', 'T'], ['analysis', 'N'], ['results', 'R'], ['implications', 'I'], ['limitations', 'L']];
  const KINDS = { fact: ['◆', 'fact: established knowledge taken as given'], method: ['⚙', 'method: how something was done'], finding: ['▲', 'finding: observed or measured in this work'], claim: ['✦', 'claim: the authors’ interpretation, argument or proposal'], gap: ['○', 'gap: a caveat or something not addressed'] };
  const cap = (k) => k[0].toUpperCase() + k.slice(1);
  const emph = (text) => esc(text).replace(/\*\*(.+?)\*\*/, '<b>$1</b>');  // the model marks each item's key phrase with **…**
  const structItem = (it, id) => `<li id="${id}" class="${it.highlight ? 'hi' : ''}" data-kind="${esc(it.kind || '')}">
      ${it.kind ? `<span class="k k-${it.kind}" title="${esc(KINDS[it.kind]?.[1] || it.kind)}">${KINDS[it.kind]?.[0] || '•'}</span>` : ''}<span class="n">${id}</span>
      ${emph(it.text)}${it.sources?.length ? ` <span class="muted small">[${it.sources.map((s) => `<abbr title="${esc(S.references?.[s] || s)}">${esc(s)}</abbr>`).join(', ')}]</span>` : ''}${it.based_on?.length ? ` <span class="small muted">rests on</span> ${it.based_on.map((r) => `<a class="chip" href="#${esc(r)}">${esc(r)}</a>`).join('')}` : ''}${it.evidence && it.evidence !== 'not stated' ? `<div class="ev">${it.section ? `<span class="sec">${a.pmcid ? `<a href="https://pmc.ncbi.nlm.nih.gov/articles/${esc(a.pmcid)}/">${esc(it.section)}</a>` : esc(it.section)}</span> ` : ''}“${esc(it.evidence)}”</div>` : ''}</li>`;
  const present = SECTIONS.filter(([k]) => S?.[k]?.length);
  const structure = S ? `
    ${S.source === 'pmc-full-text' ? '<p class="small muted">Extracted from the PMC full text; each item carries the span it was read from.</p>' : `
    <div class="flash"><b>No full text was available for this paper.</b> Everything below was extracted from the title and abstract alone,
    so design, data, analysis and limitations are thin or guessed, and no assumption can be tied to a cited reference. Treat this tab as a sketch.
    ${S.abstract ? `<p><b>The abstract, in full, as the model saw it:</b></p><p>${esc(S.abstract)}</p>` : ''}</div>`}
    <div class="struct">
      <nav class="toc">
        <ul>${present.map(([k]) => `<li><a href="#s-${k}">${cap(k)}</a> <span class="muted">${S[k].length}</span></li>`).join('')}</ul>
        <label><input type="checkbox" id="hi-only"> highlights only</label>
        <label><input type="checkbox" id="ev-on"> show evidence spans</label>
        <h4>Kinds of statement</h4>
        <div class="legend">${Object.entries(KINDS).map(([k, [g, t]]) => [k, g, t, present.reduce((n, [s]) => n + S[s].filter((it) => it.kind === k).length, 0)]).filter(([, , , n]) => n).sort((a, b) => b[3] - a[3])
          .map(([k, g, t, n]) => `<label class="k k-${k}" title="${esc(t)}"><input type="checkbox" id="kind-${k}"> ${g} ${k} <span class="muted">${n}</span></label>`).join('')}</div>
      </nav>
      <div class="body">
      <h3>Question</h3><p class="q">${esc(S.question)}</p>
      ${present.map(([k, L]) => `<section id="s-${k}"><h3>${cap(k)}</h3><ul class="items">${S[k].map((it, i) => structItem(it, `${L}${i + 1}`)).join('')}</ul></section>`).join('')}
      </div>
    </div>` : '<p class="muted">Not extracted.</p>';
  const KIND = { 'cited-as-claimed': ['a', 'Cited as claimed'], 'cited-for-something-else': ['b', 'Cited for something else'], 'claimed-but-not-cited': ['c', 'Claimed but not cited'] };
  const comparison = d.comparison ? `<ul>${d.comparison.points.map((p) => `<li><span class="kind ${KIND[p.kind]?.[0]}">${esc(KIND[p.kind]?.[1] || p.kind)}</span>${esc(p.text)}</li>`).join('')}</ul>` : '<p class="muted">Not compared.</p>';

  return {
    anchor: a,
    years: d.years,
    nums: `<div><b>${fmt(a.cited_by_count)}</b><span>citations in OpenAlex</span></div><div><b>${esc(d.generated)}</b><span>report generated</span></div><div><b>$${(d.cost_usd ?? 0).toFixed(2)}</b><span>LLM cost, all reports so far</span></div>`,
    panels: {
      backscatter: `${INTRO.backscatter}
        <h2>Overall</h2>
        ${claims(d.overall, C)}
        <h2>By time window</h2>
        <div class="tabs win">${wins.map((w) => `<button data-w="${esc(w)}" class="${w === first ? 'on' : ''}">${esc(WINDOW_LABEL[w] || w)}</button>`).join('')}</div>
        <div id="win">${windowPanel(first)}</div>`,
      anatomy: INTRO.anatomy + structure,
      comparison: INTRO.comparison + comparison,
    },
    note: 'Roles were assigned per passage by Claude Haiku from Europe PMC full-text paragraphs (with section) or Semantic Scholar citation sentences; syntheses and the argument structure by Claude Opus. Samples are seeded random draws from citers with a retrievable passage, so paywalled citers are under-represented.',
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
// Header: the "Examples" select lists the precomputed reports, the box takes any DOI for a live look-up.
// ponytail: a plain <select> is fine while there are a few dozen reports; a searchable picker if it grows past that.
INDEX.then((index) => {
  document.getElementById('examples').insertAdjacentHTML('beforeend', index.map((e) => `<option value="${esc(e.doi)}">${esc(e.title)}</option>`).join(''));
});
doi ? paper(doi, q.get('tab')) : home();
