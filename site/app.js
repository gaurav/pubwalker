// pubwalker site. No build step, no dependencies. Two modes:
//   #/paper/<slug>  precomputed report from data/<slug>.json (pipeline output)
//   #/live/<doi>    keyless live look-up: OpenAlex citers + Semantic Scholar contexts, no LLM
const app = document.getElementById('app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ROLES = ['uses-tool-or-method', 'uses-data', 'background-claim', 'compares-against', 'extends-or-modifies', 'critiques-or-contradicts', 'incidental'];
const WINDOW_LABEL = { 'last-12-months': 'Last 12 months', 'last-5-years': 'Last 5 years', 'all-time': 'All time' };
const fmt = (n) => (n ?? 0).toLocaleString();

const route = () => {
  const [, kind, ...rest] = location.hash.split('/');
  if (kind === 'paper' && rest[0]) return paper(rest[0]);
  if (kind === 'live' && rest.length) return live(decodeURIComponent(rest.join('/')));
  return home();
};
window.addEventListener('hashchange', route);
route();

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}

// ---------- home ----------
async function home() {
  let index = [];
  try { index = await json('data/index.json'); } catch { /* no precomputed reports yet */ }
  app.innerHTML = `
    <h1>What is this paper used for?</h1>
    <p>Two questions about any paper, answered from the papers that cite it and from its own text:
    <b>what role does it play in the literature</b> (a tool people run, a finding people build on, a name in a list), and
    <b>what does its argument rest on</b>. Reports below were produced by the <a href="https://github.com/gaurav/pubwalker">pipeline</a>
    with a cheap model classifying each citing passage and a stronger one synthesising; every claim links to its evidence.</p>
    <h2>Reports</h2>
    ${index.length ? index.map((e) => `
      <div class="card">
        <a class="title" href="#/paper/${esc(e.slug)}">${esc(e.title)}</a>
        <div class="muted small">${esc(e.venue || '')} ${esc(e.year || '')} · doi:${esc(e.doi)}</div>
        <div class="nums">
          <div><b>${fmt(e.cited_by_count)}</b><span>citations (OpenAlex)</span></div>
          ${Object.entries(e.windows || {}).map(([w, n]) => `<div><b>${fmt(n)}</b><span>${esc(WINDOW_LABEL[w] || w)}</span></div>`).join('')}
        </div>
      </div>`).join('') : '<p class="muted">No precomputed reports yet.</p>'}
    <h2>Try any DOI (live, no LLM)</h2>
    <p class="small muted">Fetches citing works from OpenAlex and citation sentences from Semantic Scholar directly in your browser.
    Semantic Scholar's own coarse "intents" stand in for the role classification. Run the pipeline locally for the full report.</p>
    <form class="live" onsubmit="location.hash='#/live/'+encodeURIComponent(this.doi.value.trim().replace(/^https?:\\/\\/doi.org\\//,''));return false">
      <input name="doi" placeholder="10.1126/science.1225829" required>
      <button>Look up</button>
    </form>`;
}

// ---------- shared pieces ----------
const bars = (counts, colorFn) => {
  const max = Math.max(1, ...Object.values(counts));
  return `<div class="bars">${Object.entries(counts).map(([k, n]) => `
    <span>${esc(k)}</span><div><div class="bar" style="width:${(100 * n / max).toFixed(1)}%;${colorFn ? 'background:' + colorFn(k) : ''}"></div></div><span class="n">${fmt(n)}</span>`).join('')}</div>`;
};
const roleColor = (r) => `var(--r-${r})`;
const roleBadge = (r) => r ? `<span class="role" style="background:${roleColor(r)}">${esc(r)}</span>` : '';

const yearChart = (years) => {
  if (!years?.length) return '';
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
    <summary>${roleBadge(c.role?.role)} <b>${esc(c.title)}</b> <span class="muted">(${esc(c.year)}, ${esc(c.venue || c.type || '')})</span></summary>
    <div class="small muted">${links(c)}${c.role ? ` · stance: ${esc(c.role.stance)} · confidence: ${esc(c.role.confidence)}` : ''}</div>
    ${c.role ? `<p><b>Used for:</b> ${esc(c.role.what_for)}${c.role.combined_with?.length ? ` <span class="muted">· with ${esc(c.role.combined_with.join(', '))}</span>` : ''}</p>` : ''}
    ${(c.passages || []).map((p) => `<div class="pass"><div class="src">${p.source === 'epmc' ? 'Europe PMC full text' : 'Semantic Scholar context'}${p.section ? ` · ${esc(p.section)}` : ''}</div>${esc(p.text)}</div>`).join('')}
  </details>`;

const claims = (s, citers) => s ? `
  <ol class="claims">${s.claims.map((cl) => `<li>${esc(cl.text)} ${cl.cites.map((id) => `<a class="chip" href="#c-${esc(id)}" title="${esc(citers[id]?.title || id)}" onclick="show('${esc(id)}')">${esc(id)}</a>`).join('')}</li>`).join('')}</ol>
  ${s.follow_ups?.length ? `<h3>Follow-up questions</h3><ul>${s.follow_ups.map((q) => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}` : '<p class="muted">Not synthesised.</p>';

window.show = (id) => { const d = document.getElementById(`c-${id}`); if (d) { d.open = true; d.scrollIntoView({ block: 'center' }); } };

// ---------- precomputed report ----------
async function paper(slug) {
  app.innerHTML = '<p class="muted">Loading report…</p>';
  let d;
  try { d = await json(`data/${slug}.json`); } catch (e) { app.innerHTML = `<p>Could not load <code>data/${esc(slug)}.json</code>: ${esc(e.message)}</p>`; return; }
  const a = d.anchor, C = d.citers, wins = Object.keys(d.windows);
  let current = wins[wins.length - 1];
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
  const structItem = (it) => `<dd>${esc(it.text)}${it.sources?.length ? ` <span class="muted small">[${it.sources.map((s) => `<abbr title="${esc(S.references?.[s] || s)}">${esc(s)}</abbr>`).join(', ')}]</span>` : ''}${it.evidence && it.evidence !== 'not stated' ? `<div class="ev">“${esc(it.evidence)}”</div>` : ''}</dd>`;
  const structure = S ? `
    <p class="small muted">Extracted from ${S.source === 'pmc-full-text' ? 'the PMC full text' : 'the abstract only, so design, data and analysis are thin'}; each item carries the span it was read from.</p>
    <dl class="struct">
      <dt>Question</dt><dd>${esc(S.question)}</dd>
      ${['assumptions', 'design', 'data', 'analysis', 'results', 'conclusions', 'implications', 'limitations'].filter((k) => S[k]?.length).map((k) => `<dt>${esc(k[0].toUpperCase() + k.slice(1))}</dt>${S[k].map(structItem).join('')}`).join('')}
    </dl>` : '<p class="muted">Not extracted.</p>';
  const KIND = { 'cited-as-claimed': ['a', 'Cited as claimed'], 'cited-for-something-else': ['b', 'Cited for something else'], 'claimed-but-not-cited': ['c', 'Claimed but not cited'] };
  const comparison = d.comparison ? `<ul>${d.comparison.points.map((p) => `<li><span class="kind ${KIND[p.kind]?.[0]}">${esc(KIND[p.kind]?.[1] || p.kind)}</span>${esc(p.text)}</li>`).join('')}</ul>` : '<p class="muted">Not compared.</p>';

  app.innerHTML = `
    <p class="small"><a href="#/">← all reports</a></p>
    <h1>${esc(a.title)}</h1>
    <div class="muted">${esc(a.venue || '')} ${esc(a.year || '')} · ${links(a)}</div>
    <div class="nums"><div><b>${fmt(a.cited_by_count)}</b><span>citations in OpenAlex</span></div><div><b>${esc(d.generated)}</b><span>report generated</span></div><div><b>$${(d.cost_usd ?? 0).toFixed(2)}</b><span>LLM cost, all reports so far</span></div></div>
    ${yearChart(d.years)}
    <h2>Overall</h2>
    ${claims(d.overall, C)}
    <h2>By time window</h2>
    <div class="tabs">${wins.map((w) => `<button data-w="${esc(w)}" class="${w === current ? 'on' : ''}">${esc(WINDOW_LABEL[w] || w)}</button>`).join('')}</div>
    <div id="win">${windowPanel(current)}</div>
    <h2>The paper's own argument</h2>
    ${structure}
    <h2>Claimed versus cited</h2>
    ${comparison}
    <p class="small muted">Roles were assigned per passage by Claude Haiku from Europe PMC full-text paragraphs (with section) or Semantic Scholar citation sentences; syntheses and the argument structure by Claude Opus. Samples are seeded random draws from citers with a retrievable passage, so paywalled citers are under-represented.</p>`;
  app.querySelector('.tabs').addEventListener('click', (e) => {
    const w = e.target.dataset.w; if (!w) return;
    current = w;
    app.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.w === w));
    document.getElementById('win').innerHTML = windowPanel(w);
  });
}

// ---------- live mode ----------
async function live(doi) {
  app.innerHTML = `<p class="small"><a href="#/">← home</a></p><p class="muted">Looking up ${esc(doi)}…</p>`;
  const oa = (path, params) => json(`https://api.openalex.org${path}?${new URLSearchParams({ mailto: 'pubwalker@example.org', ...params })}`);
  try {
    const w = await oa(`/works/https://doi.org/${doi}`, { select: 'id,doi,ids,title,publication_year,cited_by_count,primary_location' });
    const id = w.id.split('/').pop();
    const today = new Date(), iso = (d) => d.toISOString().slice(0, 10);
    const since = (days) => iso(new Date(today - days * 864e5));
    const [y1, y5, byYear] = await Promise.all([
      oa('/works', { filter: `cites:${id},from_publication_date:${since(365)}`, 'per-page': 1 }),
      oa('/works', { filter: `cites:${id},from_publication_date:${since(5 * 365 + 1)}`, 'per-page': 1 }),
      oa('/works', { filter: `cites:${id}`, group_by: 'publication_year', 'per-page': 1 }),
    ]);
    const years = byYear.group_by.map((g) => [+g.key, g.count]).filter(([y]) => y > 1900).sort((a, b) => a[0] - b[0]);
    const anchor = { id, doi: (w.doi || '').replace('https://doi.org/', ''), pmid: w.ids?.pmid?.split('/').pop(), title: w.title, year: w.publication_year, venue: w.primary_location?.source?.display_name, cited_by_count: w.cited_by_count };
    app.innerHTML = `
      <p class="small"><a href="#/">← home</a></p>
      <h1>${esc(anchor.title)}</h1>
      <div class="muted">${esc(anchor.venue || '')} ${esc(anchor.year || '')} · ${links(anchor)}</div>
      <div class="nums">
        <div><b>${fmt(w.cited_by_count)}</b><span>citations (OpenAlex)</span></div>
        <div><b>${fmt(y1.meta.count)}</b><span>last 12 months</span></div>
        <div><b>${fmt(y5.meta.count)}</b><span>last 5 years</span></div>
      </div>
      ${yearChart(years)}
      <h2>Citation sentences from Semantic Scholar</h2>
      <div id="s2" class="muted">Fetching…</div>
      <p class="small muted">Live mode stops here. The pipeline adds: Europe PMC full-text paragraphs with their section, a role for every passage, per-window syntheses with linked evidence, and the paper's argument structure.</p>`;
    const s2 = document.getElementById('s2');
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
    app.innerHTML += `<p class="flash">Lookup failed: ${esc(e.message)}. Check the DOI, or try again if a rate limit was hit.</p>`;
  }
}
