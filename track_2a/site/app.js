/* Gegenprobe app: Lookup | Parliaments | Repair queue | About. Static data under data/ (gegenprobe.app.build).
   Vanilla JS, no dependency, no third-party request. Every number outside the per-affair data comes from
   core.bound (bound to its claim by claims_app.json). Routes: #/ #/affair/<id> #/parliaments #/parliament/<key>
   #/queue #/about (query strings after "?"). */
'use strict';
(() => {
  // ------------------------------------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
  class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
  const raw = (s) => new Raw(String(s));
  const html = (strings, ...vals) => raw(strings.reduce((acc, s, i) => {
    const v = vals[i - 1];
    const out = v instanceof Raw ? v.s : Array.isArray(v) ? v.map((x) => (x instanceof Raw ? x.s : esc(x))).join('') : esc(v);
    return acc + out + s;
  }));
  const fmt = (n) => (n == null ? '' : Number(n).toLocaleString('en-US'));
  const share = (k, n) => (n ? (100 * k / n).toFixed(1) + '%' : '');
  const ddmmyyyy = (d) => (d && /^\d{4}-\d\d-\d\d/.test(d) ? d.slice(8, 10) + '.' + d.slice(5, 7) + '.' + d.slice(0, 4) : d || '');
  const fold = (s) => String(s || '').toLowerCase().replace(/ß/g, 'ss').replace(/œ/g, 'oe').replace(/æ/g, 'ae').replace(/ø/g, 'o')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '');
  const numKey = (s) => fold(s).replace(/\s+/g, '');
  const toast = (msg) => {
    const t = document.createElement('div');
    t.className = 'toast';
    t.setAttribute('role', 'status');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2200);
  };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const download = (name, text, type) => {
    const url = URL.createObjectURL(new Blob([text], { type: type || 'text/plain;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const csvCell = (v) => { const s = String(v == null ? '' : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const csv = (rows) => rows.map((r) => r.map(csvCell).join(',')).join('\n') + '\n';

  const cache = new Map();
  const getJSON = (url) => {
    if (!cache.has(url)) {
      const once = () => fetch(url).then((r) => { if (!r.ok) throw new Error(url + ': HTTP ' + r.status); return r.json(); });
      const p = once().catch(() => new Promise((res) => setTimeout(res, 400)).then(once));  // one retry
      p.then((v) => { p.v = v; }, () => { cache.delete(url); });
      cache.set(url, p);
    }
    return cache.get(url);
  };
  const getText = (url) => {
    if (!cache.has(url)) cache.set(url, fetch(url).then((r) => { if (!r.ok) throw new Error(url + ': HTTP ' + r.status); return r.text(); }));
    return cache.get(url);
  };

  // ------------------------------------------------------------------------------------------ data
  let C = null;            // core.json
  let I = null;            // index.json
  let rowBody = null;      // row -> body index
  let byId = null;         // OPD id -> row
  let numFold = null;      // folded affair numbers
  const B = {};            // body key -> body

  async function boot() {
    C = await getJSON('data/core.json');
    C.bodies.forEach((b, i) => { b.i = i; B[b.key] = b; });
    I = await getJSON('data/index.json');
    const n = I.id.length;
    const yr = new Uint16Array(n);
    const ty = new Uint8Array(n);
    for (let r = 0; r < n; r++) {
      const c = I.yr.charCodeAt(r);
      yr[r] = c > 0x20 ? C.year0 + c - 0x21 : 0;
      ty[r] = I.ty.charCodeAt(r) - 0x30;
    }
    I.yr = yr;
    I.ty = ty;
    rowBody = new Uint16Array(n);
    C.bodies.forEach((b) => rowBody.fill(b.i, b.start, b.start + b.n));
    byId = new Map();
    numFold = new Array(n);
    for (let r = 0; r < n; r++) { byId.set(I.id[r], r); numFold[r] = numKey(I.num[r]); }
  }
  const shardOf = (r) => {
    const b = C.bodies[rowBody[r]];
    const k = Math.floor((r - b.start) / C.shard_rows);
    return [b.shard + k, (r - b.start) % C.shard_rows];
  };
  async function detailRow(r) {
    const [s, o] = shardOf(r);
    const rows = await getJSON('data/s/' + s + '.json');
    const x = rows[o];
    return { id: x[0], tde: x[1], tfr: x[2], tit: x[3], typeRaw: x[4], sub: x[5], subSrc: x[6], ans: x[7], url: x[8], link: x[9],
      fix: x[10], cand: x[11], flags: x[12] };
  }
  // list titles: data/n/<shard>.json, a few requests at a time; a failed one leaves its rows on '…'
  async function titlesFor(rows) {
    const need = Array.from(new Set(rows.map((r) => shardOf(r)[0])));
    for (let k = 0; k < need.length; k += 6) {
      await Promise.allSettled(need.slice(k, k + 6).map((s) => getJSON('data/n/' + s + '.json')));
    }
  }
  let titleWords = [];  // folded query words: a list shows the title language they match
  const titleNow = (r) => {
    const [s, o] = shardOf(r);
    const p = cache.get('data/n/' + s + '.json');
    if (!p || !p.v) return null;
    const t = p.v[o];
    if (!Array.isArray(t)) return t;
    const hit = titleWords.length ? t.find((x) => { const f = fold(x); return titleWords.some((w) => new RegExp('(^|[^a-z0-9])' + w).test(f)); }) : null;
    return hit || t[0];
  };

  // status code -> [class, marker, short label]
  const HASH_LINE = 'OPD\u2019s document hash is sha256(body key + parent type + URL): a relink changes the hash and the files.openparldata.ch address. OPD decides whether a relinked document keeps its old identifier; the dry-run plan writes the new one.';
  // an explanation folded behind a [?] toggle (details/summary: keyboard and screen-reader accessible)
  const why = (label, body, cls) => html`<details class="q${cls ? ' ' + cls : ''}"><summary>[?]${label ? ' ' + label : ''}</summary><div>${body}</div></details>`;
  const TIER = { agenda_join: 'agenda join', be_verified: 'Bern: verified', be_review: 'Bern: check failed', be_fetch: 'Bern: verified',
    curia: 'Curia Vista', exact_doc_date: 'document date', exact_any_printed_date: 'printed date', date_window: 'date window',
    review: 'review', identity_wording_only: 'wording only' };
  const tierShort = (t) => TIER[t] || String(t || '').replace(/_/g, ' ');
  const ST = {
    a: ['attached', '[x]', 'attached'], o: ['oral', '[o]', 'oral answer'],
    R: ['repair', '[→]', 'relink'], B: ['repair', '[→]', 'relink · hash decision'], b: ['review', '[ ]', 'relink · review'],
    T: ['repair', '[→]', 'tag'], X: ['repair', '[→]', 'extract'], F: ['repair', '[→]', 'fetch'], f: ['review', '[ ]', 'fetch · review'],
    V: ['review', '[ ]', 'review candidate'], I: ['missing', '[!]', 'missing · scan'], M: ['missing', '[!]', 'missing'],
    n: ['outside', '[-]', 'record only (no recorded answer)'],
  };
  // one partition of the statuses, the same in Lookup and on a parliament's page; 'n' (an affair outside the census,
  // shown for its v0.2 record) is in 'all' only
  const GROUPS = { all: null, missing: 'IM', review: 'bfV', repair: 'RBTXF', oral: 'o', attached: 'a' };
  const statusHTML = (code) => { const s = ST[code] || ST.M; return html`<span class="st ${s[0]}">${s[1]} ${s[2]}</span>`; };
  const bodyName = (b) => (b ? b.name : '');
  const docLink = (rel) => {
    if (!rel) return '';
    const name = rel.split('/').pop();
    const local = (C.downloads || []).find((d) => d.f === name);
    return local ? local.h : C.blob + rel;
  };

  // ------------------------------------------------------------------------------------------ search
  async function tokenRows(word) {
    const key = word.slice(0, 2);
    if (!C.token_keys.includes(key)) return new Uint8Array(I.id.length);
    let bucket;
    try { bucket = await getJSON('data/t/' + key + '.json'); } catch (e) { return new Uint8Array(I.id.length); }
    const out = new Uint8Array(I.id.length);
    const w = bucket.w;
    let lo = 0;
    let hi = w.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (w[m] < word) lo = m + 1; else hi = m; }
    for (let k = lo; k < w.length && w[k].startsWith(word); k++) {
      let r = 0;
      bucket.p[k].forEach((d, j) => { r = j === 0 ? d : r + d; out[r] = 1; });
    }
    return out;
  }
  function bodyMatches(word) {
    if (word.length < 2) return [];
    return C.bodies.filter((b) => {
      const names = [b.key, b.name, b.opd_name].map(fold);
      return names.some((n) => n === word || (word.length >= 3 && n.split(/[^a-z0-9]+/).some((p) => p.startsWith(word))));
    });
  }
  async function search(q) {
    const n = I.id.length;
    const query = q.trim();
    if (!query) return [];
    const whole = numKey(query);
    const exact = [];
    const asId = /^\d+$/.test(query) ? byId.get(Number(query)) : undefined;
    if (asId !== undefined) exact.push(asId);
    for (let r = 0; r < n; r++) if (numFold[r] === whole && r !== asId) exact.push(r);
    const words = fold(query).split(/\s+/).filter(Boolean);
    let acc = null;
    for (const w of words) {
      const m = new Uint8Array(n);
      if (/\d/.test(w)) {
        const id = /^\d+$/.test(w) ? byId.get(Number(w)) : undefined;
        if (id !== undefined) m[id] = 1;
        if (w.length >= 2) for (let r = 0; r < n; r++) if (numFold[r].includes(w)) m[r] = 1;
      } else {
        const parts = w.split(/[^a-z0-9]+/).filter((p) => p.length >= 2);
        if (!parts.length) continue;
        for (const b of bodyMatches(w)) m.fill(1, b.start, b.start + b.n);
        const toks = parts.filter((p) => p.length >= 3);
        if (toks.length) {
          let tm = null;
          for (const p of toks) {
            const t = await tokenRows(p);
            if (tm) for (let r = 0; r < n; r++) tm[r] &= t[r]; else tm = t;
          }
          for (let r = 0; r < n; r++) m[r] |= tm[r];
        }
      }
      if (acc) for (let r = 0; r < n; r++) acc[r] &= m[r]; else acc = m;
    }
    const seen = new Set(exact);
    const rest = [];
    if (acc) for (let r = 0; r < n; r++) if (acc[r] && !seen.has(r)) rest.push(r);
    rest.sort((a, b) => (I.yr[b] - I.yr[a]) || (a - b));
    return exact.concat(rest);
  }

  // ------------------------------------------------------------------------------------------ router
  const views = ['lookup', 'parliaments', 'parliament', 'queue', 'about'];
  function route() {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, qs] = h.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const params = new URLSearchParams(qs || '');
    let view = 'lookup';
    if (parts[0] === 'parliaments') view = 'parliaments';
    else if (parts[0] === 'parliament' && parts[1]) view = 'parliament';
    else if (parts[0] === 'queue') view = 'queue';
    else if (parts[0] === 'about') view = 'about';
    views.forEach((v) => { $('#v-' + v).hidden = v !== view; });
    const tab = view === 'parliament' ? 'parliaments' : view;
    $$('.tabs a').forEach((a) => { if (a.dataset.view === tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    document.title = { lookup: 'Lookup', parliaments: 'Parliaments', parliament: 'Parliament', queue: 'Repair queue', about: 'About' }[view] + ' · Gegenprobe';
    if (view === 'lookup') Lookup.show(parts[0] === 'affair' ? Number(parts[1]) : null, params.get('q') || '');
    else if (view === 'parliaments') Parliaments.show(params);
    else if (view === 'parliament') Parliament.show(parts[1], params);
    else if (view === 'queue') Queue.show(params);
    else About.show();
  }
  const setQuery = (params) => {
    const [path] = location.hash.split('?');
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== '' && v != null) qs.set(k, v); });
    const s = qs.toString();
    history.replaceState(null, '', (path || '#/') + (s ? '?' + s : ''));
  };

  // ------------------------------------------------------------------------------------------ Lookup
  const Lookup = (() => {
    let q = '';
    let hits = [];
    let shown = 0;
    let group = 'all';
    let current = null;
    let seq = 0;
    let ctx = null;          // with an affair open: the rows of its parliament and year (the list without a query)
    let ctxKey = '';
    let reveal = false;      // the next list render scrolls the open affair into view
    const PAGE = 60;
    const SHORT = 8;         // a result list shorter than this is followed by the open affair's parliament and year
    const input = () => $('#q');

    function init() {
      const seg = $('#qstatus');
      seg.innerHTML = String(html`${Object.keys(GROUPS).map((g) => html`<button type="button" data-g="${g}" aria-pressed="${g === group}">${g}</button>`)}`);
      seg.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        group = b.dataset.g;
        $$('button', seg).forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
        renderList();
      });
      let timer = null;
      input().addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => run(input().value), 160);
      });
      input().addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { const a = $('#results .rlist a'); if (a) { e.preventDefault(); a.focus(); } }
        if (e.key === 'Enter') { const a = $('#results .rlist a'); if (a) { e.preventDefault(); location.hash = a.getAttribute('href'); } }
        if (e.key === 'Escape' && input().value) { e.preventDefault(); input().value = ''; run(''); }
      });
      $('#results').addEventListener('keydown', (e) => {
        const a = e.target.closest('.rlist a');
        if (!a) return;
        const li = a.parentElement;
        if (e.key === 'ArrowDown' && li.nextElementSibling) { e.preventDefault(); $('a', li.nextElementSibling).focus(); }
        if (e.key === 'ArrowUp') { e.preventDefault(); if (li.previousElementSibling) $('a', li.previousElementSibling).focus(); else input().focus(); }
      });
      $('#results').addEventListener('click', (e) => {
        const b = e.target.closest('[data-more]');
        if (b) { shown += PAGE; renderList(true); }
        const ex = e.target.closest('[data-q]');
        if (ex) { e.preventDefault(); input().value = ex.dataset.q; run(ex.dataset.q); }
      });
    }

    async function run(text) {
      q = text;
      const my = ++seq;
      const res = await search(text);
      if (my !== seq) return;
      hits = res;
      shown = PAGE;
      titleWords = fold(text).split(/[^a-z0-9]+/).filter((w) => w.length >= 3 && !/^\d+$/.test(w));
      const params = { q: text };
      setQuery(params);
      if (!text.trim()) reveal = true;  // back to the open affair's parliament and year: show the affair
      renderList();
    }

    // numbers that differ from the query in one part (2023.RRGR.388 -> 2022.RRGR.388, 2021.RRGR.388 ...)
    function nearNumbers(text) {
      const parts = numKey(text).split(/[./_\-]/).filter(Boolean);
      if (parts.length < 2 || !/\d/.test(text)) return [];
      const out = [];
      const last = parts.length - 1;
      for (let r = 0; r < numFold.length; r++) {
        const p = numFold[r].split(/[./_\-]/);
        if (p.length !== parts.length) continue;
        let diff = 0;
        for (let k = 0; k < p.length && diff < 2; k++) if (p[k] !== parts[k]) diff++;
        if (diff === 1) out.push([r, p[last] === parts[last] ? 0 : 1]);
      }
      // the same running number in another year first, then the same year
      return out.sort((a, b) => (a[1] - b[1]) || (I.yr[b[0]] - I.yr[a[0]])).slice(0, 8).map((x) => x[0]);
    }

    function filtered(rows) {
      const g = GROUPS[group];
      return g ? rows.filter((r) => g.includes(I.st[r])) : rows;
    }

    function counts(rows) {
      const c = {};
      Object.entries(GROUPS).forEach(([k, g]) => { c[k] = g ? rows.filter((r) => g.includes(I.st[r])).length : rows.length; });
      return c;
    }

    // the open affair's parliament and year: what the list shows when there is no query (a permalink, a Try link)
    function setCtx(id) {
      const r = id == null ? undefined : byId.get(id);
      if (r === undefined) { const was = ctxKey; ctx = null; ctxKey = ''; return was !== ''; }
      const bi = rowBody[r];
      const key = bi + ':' + I.yr[r];
      if (key === ctxKey) return false;
      const b = C.bodies[bi];
      ctx = [];
      for (let k = b.start; k < b.start + b.n; k++) if (I.yr[k] === I.yr[r]) ctx.push(k);
      ctx.b = b;
      ctx.y = I.yr[r];
      ctxKey = key;
      return true;
    }
    const ctxName = () => bodyName(ctx.b) + (ctx.y ? ' · ' + ctx.y : ' · year unknown');
    const ctxMore = () => html`<a href="#/parliament/${ctx.b.key}?f=all">all of ${bodyName(ctx.b)} →</a>`;
    const shortList = () => q.trim() && current != null && ctx && filtered(hits).length < SHORT;

    const item = (r) => {
      const b = C.bodies[rowBody[r]];
      const t = titleNow(r);
      return html`<li><a href="#/affair/${I.id[r]}${q ? '?q=' + encodeURIComponent(q) : ''}" aria-current="${I.id[r] === current}">
        <span class="no">${I.num[r]}</span>${statusHTML(I.st[r])}
        <span class="t${t == null ? ' pending' : ''}" data-row="${r}">${t == null ? '…' : (t || '(no title in OPD)')}</span>
        <span class="meta">${bodyName(b)} · ${I.yr[r] || ''} · ${C.types[I.ty[r]] || ''} · OPD ${I.id[r]}</span></a></li>`;
    };
    async function fillTitles(box, rows) {
      await titlesFor(rows);
      $$('.rlist .t.pending', box).forEach((el) => {
        const t = titleNow(Number(el.dataset.row));
        if (t != null) { el.textContent = t || '(no title in OPD)'; el.classList.remove('pending'); }
      });
    }

    function layout() {
      const split = $('.split');
      const browse = !q.trim();
      split.classList.toggle('idle', browse && current == null);
      split.classList.toggle('solo', browse && current != null && !ctx);  // nothing to list: the affair takes the width
      split.classList.toggle('ctx', browse && current != null && !!ctx);  // narrow screens: the list follows the affair
    }

    async function renderList(keep) {  // keep: leave the list's scroll position (Show more)
      const box = $('#results');
      const seg = $('#qstatus');
      layout();
      if (!q.trim() && !ctx) {
        $$('button', seg).forEach((b) => { b.innerHTML = esc(b.dataset.g); });
        const bd = C.bound;
        box.innerHTML = String(html`<div class="idle-line" data-claims="lookup">
          <span title="Interventions with a recorded government answer in OpenParlData"><b>${fmt(bd.written)}</b> interventions · <b>${fmt(bd.repaired)}</b> with a proposed repair</span>
          <span class="ex"><span>Try</span><a href="#" data-q="2021.RRGR.388">2021.RRGR.388</a><a href="#" data-q="Bern 39369">Bern 39369</a><a href="#" data-q="Grundwasser">Grundwasser</a><a href="#" data-q="Lugano">Lugano</a></span></div>`);
        return;
      }
      const browse = !q.trim();
      const base = browse ? ctx : hits;
      const c = counts(base);
      $$('button', seg).forEach((b) => { b.innerHTML = String(html`${b.dataset.g}<span class="c">${fmt(c[b.dataset.g])}</span>`); });
      const list = filtered(base);
      // without a query the open affair's parliament and year are listed, far enough down to include the affair
      const at = browse && current != null ? list.indexOf(byId.get(current)) : -1;
      if (at >= shown) shown = Math.ceil((at + 1 + PAGE / 3) / PAGE) * PAGE;
      const page = list.slice(0, shown);
      const extra = shortList() ? filtered(ctx).filter((r) => !list.includes(r)).slice(0, PAGE) : [];
      const tail = extra.length ? html`<div class="rcount rsub"><span>Also in ${ctxName()}</span><span>${ctxMore()}</span></div>
        <ul class="rlist">${extra.map(item)}</ul>` : '';
      const more = page.length < list.length ? html`<div class="more"><button class="btn" type="button" data-more>Show more</button></div>` : '';
      if (!list.length) {
        const near = !browse && group === 'all' ? nearNumbers(q) : [];
        box.innerHTML = String(html`<div class="empty"><p>No match for “${browse ? ctxName() : q}”${group !== 'all' ? ' in ' + group : ''}.</p>
          ${near.length ? html`<p>Close numbers: ${near.map((r, i) => html`${i ? ' · ' : ''}<a href="#/affair/${I.id[r]}">${I.num[r]}</a> <span class="muted">${bodyName(C.bodies[rowBody[r]])}</span>`)}</p>` : ''}
          ${why('Matching', 'Numbers match anywhere in the affair number; words match the start of title words or a parliament\u2019s name.')}</div>${tail}`);
        box.scrollTop = 0;
        reveal = false;
        await fillTitles(box, extra);
        return;
      }
      const head = browse
        ? html`<div class="rcount"><span>${ctxName()}: ${fmt(list.length)} affair${list.length === 1 ? '' : 's'}</span><span>${ctxMore()}</span></div>`
        : html`<div class="rcount"><span>${fmt(list.length)} match${list.length === 1 ? '' : 'es'}</span><span>${page.length < list.length ? 'showing ' + fmt(page.length) : ''}</span></div>`;
      box.innerHTML = String(html`${head}<ul class="rlist">${page.map(item)}</ul>${more}${tail}`);
      const on = $('.rlist a[aria-current="true"]', box);
      if (on && browse && reveal) box.scrollTop = Math.max(0, on.offsetTop - box.clientHeight / 3);
      else if (!keep) box.scrollTop = 0;
      reveal = false;
      await fillTitles(box, page.concat(extra));
    }

    let first = true;
    async function show(id, qs) {
      const wasShort = shortList();
      current = id;
      const moved = setCtx(id);
      reveal = moved || first;
      if (qs !== q) { input().value = qs; await run(qs); } else if (first || (moved && !q.trim()) || shortList() !== wasShort || (moved && shortList())) renderList();
      first = false;
      $('.split').classList.toggle('has-detail', id != null);
      layout();
      $$('#results .rlist a').forEach((a) => a.setAttribute('aria-current', String(a.getAttribute('href').startsWith('#/affair/' + id + '?') || a.getAttribute('href') === '#/affair/' + id)));
      const box = $('#detail');
      if (id == null) {
        box.innerHTML = '<p class="hint">[←] Select an affair</p>';
        if (document.activeElement === document.body || !document.activeElement) input().focus();
        return;
      }
      const r = byId.get(id);
      if (r === undefined) {
        box.innerHTML = String(html`<p class="hint">OPD id ${id} is not among the interventions with a recorded government answer. <a href="${C.opd_affair.replace('{id}', id)}">Open it on OpenParlData</a>.</p>`);
        return;
      }
      box.innerHTML = '<p class="hint">Loading…</p>';
      const d = await detailRow(r);
      if (current !== id) return;
      box.innerHTML = String(Detail.render(r, d, q));
      Detail.wire(box, r, d);
    }
    return { init, show, run };
  })();

  // ------------------------------------------------------------------------------------------ Detail (one affair)
  const Detail = (() => {
    const tierText = (t) => (C.tiers[t] || t || '');
    const opdUrl = (id) => C.opd_affair.replace('{id}', id);
    const plural = (n, w) => fmt(n) + ' ' + w + (n === 1 ? '' : 's');

    function where(code, d) {
      const f = d.fix || d.cand || {};
      const doc = f.d ? html`document <b>${f.d}</b>` : '';
      const title = f.x ? html` (“${f.x}”)` : '';
      switch (code) {
        case 'a': return html`<p>Attached in OPD.</p>`;
        case 'o': return html`<p>Oral, in the sitting. No written text.</p>`;
        case 'R': return html`<p>In OPD under an agenda item for this affair: ${doc}${title}${f.n ? ', ' + f.n : ''}.</p>`;
        case 'B': case 'b': return html`<p>In OPD without a parent: ${doc}${title}. Named as this answer by the canton's open data.</p>`;
        case 'T': return html`<p>In OPD on this affair, under an unrecognised heading: ${doc}${title}.</p>`;
        case 'X': return html`<p>In OPD as a copy without usable text: ${doc}${title}. Text read${f.ex ? ' (' + f.ex + ')' : ''} and checked.</p>`;
        case 'F': case 'f': return html`<p>Not in OPD. Published by the ${f.s === 'curia' ? 'federal parliament (Curia Vista)' : 'parliament'}${f.u ? html`: <a href="${f.u}">${hostOf(f.u)}</a>` : ''}${title}.</p>`;
        case 'V': return html`<p>Candidate, not counted${f.d ? html`: ${doc}` : f.u ? html`: <a href="${f.u}">${hostOf(f.u)}</a>` : ''}${title}.</p>`;
        case 'I': return html`<p>In OPD only as a scan without text. No verified copy yet.</p>`;
        case 'M': return html`<p>Not in OPD. ${d.flags & 4 ? 'A source adapter found nothing usable.' : 'No list or source adapter has it yet.'}</p>`;
        default: return html`<p>No recorded answer in OPD: outside the census, shown for its v0.2 record.</p>`;
      }
    }
    const hostOf = (u) => { try { return new URL(u).host; } catch (e) { return u; } };
    const shortUrl = (u) => {
      try { const x = new URL(u); const p = x.pathname + x.search; return x.host + (p.length > 48 ? p.slice(0, 20) + '…' + p.slice(-24) : p); } catch (e) { return u; }
    };

    function evidence(code, d) {
      const f = d.fix || d.cand;
      if (!f) return '';
      const rows = [];
      if (f.d) rows.push(['OPD document', f.d]);
      if (f.u) rows.push(['Source document', html`<a href="${f.u}" title="${f.u}">${shortUrl(f.u)}</a>`]);
      rows.push(['Check', tierText(f.t)]);
      if (f.dn) rows.push(['Decision', 'RRB ' + f.dn + (f.dt ? ' of ' + ddmmyyyy(f.dt) : '')]);
      else if (f.dt) rows.push(['Document date', ddmmyyyy(f.dt)]);
      if (f.ev) rows.push(['OPD answer events', f.ev.split(/\s+/).map(ddmmyyyy).join(' · ')]);
      if (f.m) rows.push(['Date match', f.m]);
      if (f.c) rows.push(['Target category', f.c]);
      if (f.f) rows.push(['Listed in', html`<a href="${docLink(f.f)}">${f.f.split('/').pop()}</a>`]);
      return html`<table class="facts mono"><tbody>${rows.map(([k, v]) => html`<tr><th scope="row">${k}</th><td>${v}</td></tr>`)}</tbody></table>
        ${f.q ? html`<div class="quote">“${f.q}”</div>` : ''}`;
    }

    function fix(code, d, id) {
      const f = d.fix || d.cand || {};
      const step = { R: 'apply now', T: 'apply now', X: 'apply now', B: 'after OPD’s hash decision', b: 'after review and the hash decision', F: 'fetch', f: 'after review' }[code];
      let what = '';
      switch (code) {
        case 'R': what = html`Attach document ${f.d} to affair ${id}.`; break;
        case 'B': case 'b': what = html`Move document ${f.d} from its agenda parent to affair ${id}.`; break;
        case 'T': what = html`Set the category of document ${f.d}${f.c ? ' to ' + f.c : ''}.`; break;
        case 'X': what = html`Store the verified text of document ${f.d}${f.c ? ', category ' + f.c : ''}.`; break;
        case 'F': case 'f': what = html`Fetch the parliament's document; attach it to affair ${id}${f.c ? ', category ' + f.c : ''}.`; break;
        case 'V': what = html`Nothing is applied until a person confirms the candidate.`; break;
        default: return '';
      }
      const decide = [];
      if (f.h) {
        decide.push(html`<div class="decide">${f.p ? html`<div class="plan">plan row: hash ${String(f.hb).slice(0, 12)}… → ${String(f.ha).slice(0, 12)}… · <a href="${C.bern_plan}">apply_BE_plan.sql.txt</a></div>` : html`<div class="plan">not in the dry-run plan (verified relinks only)</div>`}
          ${why('Hash decision', HASH_LINE)}</div>`);
      }
      if (f.r || code === 'V') decide.push(html`<div class="decide">[ ] review: ${f.rr || tierText(f.t)}</div>`);
      return html`<p class="act"><b>[→] ${(f.a || '').toUpperCase()}</b>${step ? html` <span class="muted">· ${step}</span>` : ''}</p><p>${what}</p>${decide}`;
    }

    function render(r, d, q) {
      const b = C.bodies[rowBody[r]];
      const code = I.st[r];
      const s = ST[code];
      const titles = [['de', d.tde], ['fr', d.tfr], ['it', d.tit]].filter((x) => x[1]);
      const main = titles[0];
      const statusLine = {
        attached: 'Answer attached', oral: 'Oral answer', repair: 'Repair proposed', review: 'Review', missing: 'Answer missing', outside: 'No recorded answer',
      }[s[0]];
      const sub = {
        o: 'no written text expected', R: 'relink · apply now', T: 'tag · apply now', X: 'extract · apply now',
        B: 'relink · after OPD\u2019s hash decision', b: 'relink · a person checks first, then the hash decision', F: 'fetch from the parliament',
        f: 'fetch · a person checks first', V: 'a candidate, not counted', I: 'OPD holds a scan without text', M: 'not in OPD',
      }[code] || '';
      const facts = [
        ['Parliament', html`<a href="#/parliament/${b.key}">${b.name}</a>`],
        ['Type', (C.types[I.ty[r]] || '') + (d.typeRaw && d.typeRaw !== C.types[I.ty[r]] ? ' (' + d.typeRaw + ')' : '')],
        ['Submitted', d.flags & 1 ? html`<abbr title="OPD’s begin date is its load timestamp">unknown</abbr>` : d.subSrc === 'begin_date' ? html`<abbr title="OPD begin date">${ddmmyyyy(d.sub)}</abbr>` : ddmmyyyy(d.sub)],
        [raw('<abbr title="OPD answer event">Answered</abbr>'), ddmmyyyy(d.ans)],
        ['Link status', d.link ? (d.link === 'absent' ? html`<abbr title="no answer document found">absent</abbr>` : d.link.replace(/_/g, ' ')) : ''],
        ['Date trust', b.date_trust ? b.date_trust.replace(/_/g, ' ') : ''],
        ['OPD id', String(I.id[r])],
      ];
      const back = q ? '#/?q=' + encodeURIComponent(q) : '#/';
      return html`<a class="backlink only-mobile" href="${back}">← ${q ? 'Results' : 'Search'}</a>
        <div class="dhead"><b>${I.num[r]}</b><span>${b.name}</span><span>${I.yr[r] || ''}</span>
          <span class="perma"><button class="btn" type="button" data-copy="#/affair/${I.id[r]}" title="Copy a link to this affair">Copy link</button></span></div>
        <h1 class="dtitle">${main ? main[1] : '(no title in OPD)'}</h1>
        ${titles.slice(1).map(([lg, t]) => html`<p class="alt"><span class="lg">${lg.toUpperCase()}</span>${t}</p>`)}
        <div class="status ${s[0]}">${s[1]} ${statusLine}${sub ? html`<span class="s2">${sub}</span>` : ''}</div>
        <div class="kv">${facts.filter((x) => String(x[1])).map(([k, v]) => html`<div><span class="lbl">${k}</span><div class="v">${v}</div></div>`)}</div>
        <p class="go-links"><a href="${opdUrl(I.id[r])}">OpenParlData</a>${d.url ? html`<a href="${d.url}">Parliament's page</a>` : ''}${(d.fix || d.cand || {}).u ? html`<a href="${(d.fix || d.cand).u}">Answer document</a>` : ''}</p>
        <h2>Answer</h2>
        <div class="prose">${where(code, d)}</div>
        ${evidence(code, d)}
        ${(d.fix || code === 'V') ? html`<h2>${code === 'V' ? 'Review' : 'Fix'}</h2><div class="prose">${fix(code, d, I.id[r])}</div>` : ''}
        <div id="record"></div>`;
    }

    function wire(box, r, d) {
      $$('[data-copy]', box).forEach((btn) => btn.addEventListener('click', () => {
        const url = location.origin + location.pathname + btn.dataset.copy;
        (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => toast('Link copied: ' + btn.dataset.copy),
          () => { history.replaceState(null, '', btn.dataset.copy); toast('Link in the address bar'); });
      }));
      if (d.flags & 2) Record.load($('#record', box), I.id[r]);
    }
    return { render, wire, tierText, plural };
  })();

  // ------------------------------------------------------------------------------------------ Record (v0.2)
  const Record = (() => {
    const GAP = { not_applicable: 'not applicable', present_unanchored: 'printed, not anchored', not_in_document: 'not in the document',
      none_printed: 'none printed', not_extracted: 'not extracted', not_carried: 'not carried' };
    const label = (p, c) => {
      if (/^documents\.\d+\.parts$/.test(p)) return 'parts of ' + (c && c.doc ? c.doc : 'a document');
      const segs = p.split('.');
      const out = [];
      segs.forEach((s, i) => {
        if (/^\d+$/.test(s)) { if (segs[i - 1] === 'items') out.push('item ' + (Number(s) + 1)); return; }
        if (s === 'items' || s === 'name' || s === 'date') return;
        out.push(s.replace(/_/g, ' '));
      });
      return out.join(' · ');
    };
    async function load(box, id) {
      let rec;
      try { rec = await getJSON('data/r/' + id + '.json'); } catch (e) { box.innerHTML = ''; return; }
      const main = rec.cells.filter((c) => !/^qa\.\d+\.items\./.test(c.p));
      const qa = rec.cells.filter((c) => /^qa\.\d+\.items\./.test(c.p));
      const where = (c) => (c.pg != null ? 'p. ' + c.pg : '') + (c.cs != null ? ' · ' + c.cs + '–' + c.ce : '');
      const row = (c, i) => {
        const how = c.ru || c.src || '';
        if (c.k === 'v') {
          return html`<tr data-i="${i}" class="${c.bb ? 'box' : ''}" tabindex="${c.bb ? 0 : -1}"><td class="f mono">${label(c.p, c)}</td><td class="v">${c.v}${c.q ? html`<div class="mono muted">“${c.q}”</div>` : ''}${how ? html`<div class="how">${how}</div>` : ''}</td>
            <td class="r">${(c.role || '').replace(/_/g, ' ')}</td><td class="w">${where(c)}</td><td class="r">${c.rt}</td></tr>`;
        }
        return html`<tr data-i="${i}"><td class="f mono">${label(c.p, c)}</td><td class="v"><span class="gap">[–] ${GAP[c.nr] || (c.nr || '').replace(/_/g, ' ')}</span>${c.e ? why('', c.e, 'inline') : ''}</td>
          <td class="r">${(c.role || '').replace(/_/g, ' ')}</td><td class="w"></td><td class="r">${c.rt || ''}</td></tr>`;
      };
      const idx = new Map(rec.cells.map((c, i) => [c, i]));
      const table = (cells) => html`<div class="recwrap"><table class="rec"><thead><tr><th>Field</th><th title="A value, or a typed gap [–] with its reason">Value</th><th>Role</th><th title="Page · character span">Where</th><th>Route</th></tr></thead>
        <tbody>${cells.map((c) => row(c, idx.get(c)))}</tbody></table></div>`;
      // page outlines: one per (document, page) with located values
      const pages = new Map();
      rec.cells.forEach((c, i) => {
        if (!c.bb) return;
        const key = c.doc + '#' + c.bpg;
        if (!pages.has(key)) pages.set(key, []);
        c.bb.forEach((b) => pages.get(key).push([i, b]));
      });
      const outline = (key, boxes) => {
        const size = rec.pages[key] || [595, 842];
        const [w, hgt] = size;
        const lines = [];
        const margin = Math.round(w / 12);
        for (let y = margin * 1.2; y < hgt - margin; y += margin * 0.44) lines.push(html`<line x1="${margin}" x2="${w - margin}" y1="${y}" y2="${y}"></line>`);
        return html`<div class="page"><svg viewBox="0 0 ${w} ${hgt}" role="img" aria-label="Page outline with the located values">${lines}
          ${boxes.map(([i, b]) => html`<rect class="b" data-i="${i}" x="${b[0]}" y="${b[1]}" width="${Math.max(b[2] - b[0], 4)}" height="${Math.max(b[3] - b[1], 4)}"></rect>`)}</svg>
          <div class="pl">${key.replace('#', ' · p. ')}</div></div>`;
      };
      box.innerHTML = String(html`<h2>Record v0.2</h2>
        <p class="hint">${rec.label} · schema ${rec.v} · ${rec.docs.map((d, k) => html`${k ? ' · ' : ''}<a href="${d.url}">${d.id}</a> ${d.role}${d.n ? ' ' + d.n + ' p.' : ''}`)}</p>
        ${pages.size ? html`<div class="pages">${Array.from(pages.entries()).map(([k, b]) => outline(k, b))}</div>` : ''}
        ${table(main)}
        ${qa.length ? html`<details class="more-cells"><summary>Question–answer pairs (${qa.length})</summary>${table(qa)}</details>` : ''}`);
      const on = (i, v) => {
        $$('[data-i="' + i + '"]', box).forEach((el) => el.classList.toggle('on', v));
      };
      box.addEventListener('mouseover', (e) => { const t = e.target.closest('[data-i]'); if (t) on(t.dataset.i, true); });
      box.addEventListener('mouseout', (e) => { const t = e.target.closest('[data-i]'); if (t) on(t.dataset.i, false); });
      box.addEventListener('focusin', (e) => { const t = e.target.closest('tr[data-i]'); if (t) on(t.dataset.i, true); });
      box.addEventListener('focusout', (e) => { const t = e.target.closest('tr[data-i]'); if (t) on(t.dataset.i, false); });
    }
    return { load };
  })();

  // ------------------------------------------------------------------------------------------ Parliaments
  const LEVELS = { all: null, cantons: ['canton'], communes: ['city', 'municipality'], federal: ['federal', 'country'] };
  const BAR_W = 100;
  const BAR_H = 8;
  const covBar = (b, cls) => {
    const t = b.written ? BAR_W * b.attached / b.written : 0;
    const a = b.written ? BAR_W * (b.attached + b.repaired) / b.written : 0;
    return html`<svg class="${cls || ''}" viewBox="${[0, 0, BAR_W, BAR_H].join(' ')}" preserveAspectRatio="none" aria-hidden="true"><rect class="bg" width="${BAR_W}" height="${BAR_H}"></rect>
      <rect class="t1" width="${a.toFixed(2)}" height="${BAR_H}"></rect><rect class="t0" width="${t.toFixed(2)}" height="${BAR_H}"></rect></svg>`;
  };
  const Parliaments = (() => {
    const COLS = [
      ['name', 'Parliament', 'l sticky'], ['level', 'Level', 'l hm'], ['lang', 'Lang', 'l hm'],
      ['written', 'Answers', '', 'Interventions with a recorded government answer'], ['today', 'Today', '', 'Answer text attached in OPD'],
      ['after', 'After repairs', '', 'Attached plus every proposed repair'], ['gap', 'Gap', '', 'Answers without attached text = oral + repairs + open'],
      ['oral', 'Oral', '', 'Answered orally: no written text expected'],
      ['repaired', 'Repairs', '', 'Relink + tag + extract + fetch: the parliament\u2019s rows in the repair queue'],
      ['relink', 'Relink'], ['hash', 'After hash', '', 'Relinks that wait for OPD\u2019s hash decision (Bern); the other relinks are agenda joins, applied now. Bern\u2019s begin-date corrections fix another field and are not counted'],
      ['tag', 'Tag'], ['extract', 'Extract'], ['fetch', 'Fetch'], ['open', 'Open', '', 'Still without text after the repairs'], ['converter', 'Converter', 'l'],
    ];
    const val = (b, k) => ({
      today: b.written ? b.attached / b.written : 0, after: b.written ? (b.attached + b.repaired) / b.written : 0,
      relink: b.by_action.relink || 0, tag: b.by_action.tag || 0, extract: b.by_action.extract || 0, fetch: b.by_action.fetch || 0,
      hash: b.by_step.after_hash || 0,
    }[k] ?? b[k]);
    let st = { level: 'all', lang: 'all', sort: 'gap', dir: 'desc', text: '' };

    function show(params) {
      st = { level: params.get('level') || 'all', lang: params.get('lang') || 'all', sort: params.get('sort') || 'gap',
        dir: params.get('dir') || 'desc', text: params.get('text') || '' };
      render();
    }
    function rows() {
      const lv = LEVELS[st.level];
      const t = fold(st.text);
      const list = C.bodies.filter((b) => b.written > 0 && (!lv || lv.includes(b.level)) && (st.lang === 'all' || b.lang === st.lang.toUpperCase())
        && (!t || [b.name, b.opd_name, b.key].some((x) => fold(x).includes(t))));
      const k = st.sort;
      const s = st.dir === 'asc' ? 1 : -1;
      list.sort((a, b) => {
        const x = val(a, k);
        const y = val(b, k);
        return (typeof x === 'string' ? x.localeCompare(y) : x - y) * s || a.name.localeCompare(b.name);
      });
      return list;
    }
    function render() {
      const box = $('#v-parliaments');
      const list = rows();
      const langs = Array.from(new Set(C.bodies.filter((b) => b.written > 0).map((b) => b.lang).filter(Boolean))).sort();
      const sum = (k) => list.reduce((a, b) => a + val(b, k), 0);
      const tot = { written: sum('written'), attached: sum('attached'), repaired: sum('repaired') };
      const cell = (b, k) => {
        const v = val(b, k);
        if (k === 'name') return html`<td class="l sticky"><span class="pname">${b.name}</span><span class="pkey">${b.key}</span></td>`;
        if (k === 'level' || k === 'lang') return html`<td class="l hm">${v}</td>`;
        if (k === 'converter') return html`<td class="l">${v}</td>`;
        if (k === 'today') return html`<td>${share(b.attached, b.written)}</td>`;
        if (k === 'after') return html`<td><span class="cov">${share(b.attached + b.repaired, b.written)}${covBar(b)}</span></td>`;
        return html`<td class="${v ? '' : 'zero'}">${fmt(v)}</td>`;
      };
      box.innerHTML = String(html`<h1>Parliaments</h1>
        <div class="filters">
          <div class="seg" data-k="level" role="group" aria-label="Level">${Object.keys(LEVELS).map((l) => html`<button type="button" data-v="${l}" aria-pressed="${st.level === l}">${l}</button>`)}</div>
          <div class="seg" data-k="lang" role="group" aria-label="Language">${['all'].concat(langs.map((l) => l.toLowerCase())).map((l) => html`<button type="button" data-v="${l}" aria-pressed="${st.lang === l}">${l}</button>`)}</div>
          <input id="ptext" type="text" value="${st.text}" placeholder="Name" aria-label="Filter by name">
        </div>
        <div class="tablewrap"><table class="dense"><thead><tr>${COLS.map(([k, label, cls, tip]) => html`<th class="${cls || ''}" ${tip ? raw('title="' + esc(tip) + '"') : ''} ${st.sort === k ? raw('aria-sort="' + (st.dir === 'asc' ? 'ascending' : 'descending') + '"') : ''}><button type="button" data-sort="${k}">${label}</button></th>`)}</tr></thead>
          <tbody>${list.map((b) => html`<tr class="go" tabindex="0" data-key="${b.key}">${COLS.map(([k]) => cell(b, k))}</tr>`)}</tbody>
          <tfoot><tr><td class="l sticky">${list.length} parliament${list.length === 1 ? '' : 's'}</td><td class="hm"></td><td class="hm"></td><td>${fmt(tot.written)}</td><td>${share(tot.attached, tot.written)}</td>
            <td>${share(tot.attached + tot.repaired, tot.written)}</td><td>${fmt(sum('gap'))}</td><td>${fmt(sum('oral'))}</td><td>${fmt(tot.repaired)}</td><td>${fmt(sum('relink'))}</td><td>${fmt(sum('hash'))}</td><td>${fmt(sum('tag'))}</td>
            <td>${fmt(sum('extract'))}</td><td>${fmt(sum('fetch'))}</td><td>${fmt(sum('open'))}</td><td></td></tr></tfoot></table></div>`);
      const upd = (patch) => { Object.assign(st, patch); setQuery({ level: st.level === 'all' ? '' : st.level, lang: st.lang === 'all' ? '' : st.lang, sort: st.sort === 'gap' ? '' : st.sort, dir: st.dir === 'desc' ? '' : st.dir, text: st.text }); render(); };
      $$('.seg', box).forEach((seg) => seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) upd({ [seg.dataset.k]: b.dataset.v }); }));
      $('#ptext', box).addEventListener('input', (e) => {
        const pos = e.target.selectionStart;
        upd({ text: e.target.value });
        const el = $('#ptext');
        el.focus();
        el.setSelectionRange(pos, pos);
      });
      $$('th button', box).forEach((b) => b.addEventListener('click', () => {
        const k = b.dataset.sort;
        upd(st.sort === k ? { dir: st.dir === 'asc' ? 'desc' : 'asc' } : { sort: k, dir: ['name', 'level', 'lang', 'converter'].includes(k) ? 'asc' : 'desc' });
        const again = $('th button[data-sort="' + k + '"]');
        if (again) again.focus();
      }));
      $$('tbody tr.go', box).forEach((tr) => {
        tr.addEventListener('click', () => { location.hash = '#/parliament/' + tr.dataset.key; });
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') location.hash = '#/parliament/' + tr.dataset.key; });
      });
    }
    return { show };
  })();

  // ------------------------------------------------------------------------------------------ Parliament page
  const Parliament = (() => {
    const FILTERS = { missing: 'IM', review: 'bfV', repair: 'RBTXF', oral: 'o', attached: 'a', all: null };
    const PAGE = 100;
    let key = null;
    let filter = 'open';
    let page = 0;

    function show(k, params) {
      key = k;
      filter = params.get('f') || 'missing';
      page = Number(params.get('p') || 0);
      render();
    }
    function rowsOf(b) {
      const g = FILTERS[filter];
      const out = [];
      for (let r = b.start; r < b.start + b.n; r++) if (I.st[r] !== 'n' && (!g || g.includes(I.st[r]))) out.push(r);
      return out;
    }
    async function render() {
      const box = $('#v-parliament');
      const b = B[key];
      if (!b) { box.innerHTML = String(html`<a class="backlink" href="#/parliaments">← Parliaments</a><p>No parliament with key ${key}.</p>`); return; }
      const list = rowsOf(b);
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      page = Math.min(page, pages - 1);
      const slice = list.slice(page * PAGE, page * PAGE + PAGE);
      const cnt = (f) => { const g = FILTERS[f]; let n = 0; for (let r = b.start; r < b.start + b.n; r++) if (I.st[r] !== 'n' && (!g || g.includes(I.st[r]))) n++; return n; };
      const hashN = b.by_step.after_hash || 0;
      const acts = C.actions.filter((a) => b.by_action[a]).map((a) => html`${a} <b>${fmt(b.by_action[a])}</b>${a === 'relink' && hashN
        ? html` (${b.by_action.relink > hashN ? fmt(b.by_action.relink - hashN) + ' now, ' : ''}${fmt(hashN)} after hash)` : ''}`);
      const form = [
        ['Level', b.level || '—'], ['Language', b.lang || '—'], ['Converter', b.converter || '—'],
        ['Answer dates', b.date_trust ? b.date_trust.replace(/_/g, ' ') : '—'],
        ['Answers', html`<b>${fmt(b.written)}</b> · gap ${fmt(b.gap)} · oral ${fmt(b.oral)} · open ${fmt(b.open)}`],
        ['Repairs', b.repaired ? html`<b>${fmt(b.repaired)}</b> · ${acts.map((a, i) => html`${i ? ' · ' : ''}${a}`)} · <a href="#/queue?b=${encodeURIComponent(b.key)}">[→] queue</a>` : '0'],
      ];
      box.innerHTML = String(html`<a class="backlink" href="#/parliaments">← Parliaments</a>
        <h1>${b.name} <span class="key">${b.key}</span></h1>
        <div class="figs two"><div><span class="big">${share(b.attached, b.written)}</span><span class="lbl">answer text today</span></div>
          <div><span class="big">${share(b.attached + b.repaired, b.written)}</span><span class="lbl">after the proposed repairs</span></div></div>
        <div class="bigbar" title="Black: text attached · grey: after the proposed repairs · blank: open or oral">${covBar(b)}</div>
        <dl class="form pairs">${form.map(([k, v], i) => html`<dt>${k}</dt><dd class="${i > 3 ? 'long' : ''}">${v}</dd>`)}</dl>
        <div class="page-body">
        <section class="sec"><h2>Interventions</h2><div class="w">
        <div class="bar"><div class="seg" id="pfilter" role="group" aria-label="Status">${Object.keys(FILTERS).map((f) => html`<button type="button" data-f="${f}" aria-pressed="${f === filter}">${f}<span class="c">${fmt(cnt(f))}</span></button>`)}</div>
          <button class="btn" type="button" id="pexport" title="The rows of this filter, with status and repair">Export CSV</button></div>
        <div class="plist" id="prows"><ul class="rlist">${slice.map((r) => html`<li><a href="#/affair/${I.id[r]}"><span class="no">${I.num[r]}</span>${statusHTML(I.st[r])}
          <span class="t pending" data-row="${r}">…</span><span class="meta">${I.yr[r] || ''} · ${C.types[I.ty[r]] || ''} · OPD ${I.id[r]}</span></a></li>`)}</ul>
          ${slice.length ? '' : html`<p class="empty">No intervention in this filter.</p>`}</div>
        ${pages > 1 ? html`<div class="pager"><button class="btn" type="button" data-p="${page - 1}" ${page === 0 ? raw('disabled') : ''}>← Previous</button>
          <span>page ${page + 1} of ${pages}</span><button class="btn" type="button" data-p="${page + 1}" ${page >= pages - 1 ? raw('disabled') : ''}>Next →</button></div>` : ''}
        </div></section>
        <section class="sec"><h2>Files</h2><div class="w">
          <ul class="files">${b.lists.map((f) => html`<li><a href="${docLink(f)}">${f.split('/').pop()}</a>${docLink(f).startsWith('http') ? html` <span class="muted">(repository)</span>` : ''}</li>`)}</ul>
          ${b.by_code.B || b.by_code.b ? why('Hash decision', HASH_LINE + ' The plan\u2019s begin-date corrections (OPD\u2019s load timestamp replaced by the submission date) fix another field and are not counted as repairs.') : ''}
        </div></section></div>`);
      $('#pfilter').addEventListener('click', (e) => { const x = e.target.closest('button'); if (x) { filter = x.dataset.f; page = 0; setQuery({ f: filter === 'missing' ? '' : filter }); render(); } });
      $$('[data-p]', box).forEach((x) => x.addEventListener('click', () => { page = Number(x.dataset.p); setQuery({ f: filter === 'missing' ? '' : filter, p: page || '' }); render(); box.scrollIntoView(); }));
      $('#pexport').addEventListener('click', () => exportRows(b, list));
      await titlesFor(slice);
      $$('#prows .t[data-row]').forEach((el) => {
        const t = titleNow(Number(el.dataset.row));
        if (t != null) { el.textContent = t || '(no title in OPD)'; el.classList.remove('pending'); }
      });
    }
    async function exportRows(b, list) {
      const btn = $('#pexport');
      btn.disabled = true;
      btn.textContent = 'Preparing…';
      const need = Array.from(new Set(list.map((r) => shardOf(r)[0])));
      for (let k = 0; k < need.length; k += 6) await Promise.all(need.slice(k, k + 6).map((s) => getJSON('data/s/' + s + '.json')));
      const out = [['affair_id', 'number', 'body', 'parliament', 'status', 'type', 'year', 'title', 'action', 'check', 'review', 'needs_hash_decision', 'opd_doc_id', 'target_url', 'opd_url']];
      for (const r of list) {
        const [s, o] = shardOf(r);
        const x = (await getJSON('data/s/' + s + '.json'))[o];
        const f = x[10] || x[11] || {};
        out.push([I.id[r], I.num[r], b.key, b.name, (ST[I.st[r]] || [])[2], C.types[I.ty[r]], I.yr[r] || '', x[1] || x[2] || x[3], f.a || '', f.t || '',
          f.r ? 'yes' : '', f.h ? 'yes' : '', f.d || '', f.u || '', C.opd_affair.replace('{id}', I.id[r])]);
      }
      download('gegenprobe_' + b.key + '_' + filter + '.csv', csv(out), 'text/csv;charset=utf-8');
      btn.disabled = false;
      btn.textContent = 'Export CSV';
    }
    return { show };
  })();

  // ------------------------------------------------------------------------------------------ Repair queue
  const Queue = (() => {
    let Q = null;
    let st = {};
    const selected = new Set();
    let page = 0;
    let open = null;
    const PAGE = 100;
    const STEPS = { now: 'apply now', after_hash: 'after the hash decision', fetch: 'fetch' };

    async function show(params) {
      const box = $('#v-queue');
      st = { b: params.get('b') || '', a: params.get('a') || '', step: params.get('step') || params.get('h') === 'yes' && 'after_hash' || '',
        t: params.get('t') || '', r: params.get('r') || '' };
      page = 0;
      if (!Q) {
        box.innerHTML = '<p class="loading">Loading the queue…</p>';
        Q = await getJSON('data/queue.json');
      }
      render();
    }
    function match(k) {
      const r = Q.i[k];
      return (!st.b || C.bodies[rowBody[r]].key === st.b) && (!st.a || C.actions[Q.a[k]] === st.a) && (!st.step || Q.step[k] === st.step)
        && (!st.t || Q.t[k] === st.t) && (!st.r || (st.r === 'review' ? Q.r[k] === 1 : Q.r[k] === 0));
    }
    function matching() { const out = []; for (let k = 0; k < Q.i.length; k++) if (match(k)) out.push(k); return out; }
    function render() {
      const box = $('#v-queue');
      const bd = C.bound;
      const list = matching();
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      page = Math.min(page, pages - 1);
      const slice = list.slice(page * PAGE, page * PAGE + PAGE);
      const bodiesWith = C.bodies.filter((b) => b.repaired > 0).sort((a, b) => a.name.localeCompare(b.name));
      const tiers = Array.from(new Set(Q.t)).sort();
      const selRelink = Array.from(selected).filter((k) => Q.s[k] === 'be' && C.actions[Q.a[k]] === 'relink');
      const selBern = selRelink.filter((k) => Q.p[k] === 1);
      const seg = (k, opts) => html`<div class="seg" data-k="${k}">${Object.entries(opts).map(([v, l]) => html`<button type="button" data-v="${v}" aria-pressed="${st[k] === v}">${l}</button>`)}</div>`;
      box.innerHTML = String(html`<h1>Repair queue</h1>
        <div class="figs" data-claims="queue"><div><span class="big">${fmt(bd.now)}</span><span class="lbl">apply now</span></div>
          <div title="Bern relinks that wait for OPD\u2019s hash decision"><span class="big">${fmt(bd.after_hash)}</span><span class="lbl">Bern, after hash decision</span></div>
          <div><span class="big">${fmt(bd.fetch)}</span><span class="lbl">fetch from parliaments</span></div></div>
        <button class="btn only-mobile" type="button" id="qf" aria-expanded="false">Filters${Object.values(st).filter(Boolean).length ? ' (' + Object.values(st).filter(Boolean).length + ' on)' : ''}</button>
        <div class="filters collapsible" id="qfilters">
          <div><label class="lbl" for="qb">Parliament</label><select id="qb"><option value="">all</option>${bodiesWith.map((b) => html`<option value="${b.key}" ${st.b === b.key ? raw('selected') : ''}>${b.name}</option>`)}</select></div>
          <div><span class="lbl">Action</span>${seg('a', { '': 'all', relink: 'relink', tag: 'tag', extract: 'extract', fetch: 'fetch' })}</div>
          <div><span class="lbl">Step</span>${seg('step', { '': 'all', now: 'now', after_hash: 'after hash', fetch: 'fetch' })}</div>
          <div><span class="lbl">Status</span>${seg('r', { '': 'all', ready: 'ready', review: 'review' })}</div>
          <div><label class="lbl" for="qt">Check</label><select id="qt"><option value="">all</option>${tiers.map((t) => html`<option value="${t}" ${st.t === t ? raw('selected') : ''}>${tierShort(t)}</option>`)}</select></div>
        </div>
        ${why('Hash decision', HASH_LINE)}
        <div class="qbar"><span class="count"><b>${fmt(list.length)}</b> row${list.length === 1 ? '' : 's'} · <b>${fmt(selected.size)}</b> selected</span>
          <button class="btn" type="button" id="qall">Select all ${fmt(list.length)}</button>
          <button class="btn" type="button" id="qnone" ${selected.size ? '' : raw('disabled')}>Clear</button>
          <button class="btn primary" type="button" id="qcsv" ${selected.size ? '' : raw('disabled')}>Export CSV</button>
          <button class="btn" type="button" id="qsql" ${selBern.length ? '' : raw('disabled')} title="${selBern.length ? 'The guarded UPDATE statements of the selected Bern relinks, copied from the dry-run plan' : 'Select Bern relinks (step: after hash) to export their statements from the dry-run plan'}">Export Bern SQL${selBern.length ? ' (' + fmt(selBern.length) + (selRelink.length > selBern.length ? ' in the plan; ' + fmt(selRelink.length - selBern.length) + ' review rows are not' : '') + ')' : ''}</button></div>
        <div class="tablewrap"><table class="dense" id="qtable"><thead><tr><th class="plain"><span class="sr">Select</span></th><th class="l plain">Number</th><th class="l plain">Parliament</th><th class="l plain">Action</th><th class="l plain hm">Step</th>
          <th class="l plain hm">Check</th><th class="l plain">Status</th><th class="l plain">Target</th></tr></thead>
          <tbody>${slice.map((k) => { const r = Q.i[k]; return html`<tr class="go ${open === k ? 'open' : ''}" tabindex="0" data-k="${k}"><td class="ck"><input type="checkbox" aria-label="Select ${I.num[r]}" data-k="${k}" ${selected.has(k) ? raw('checked') : ''}></td>
            <td class="l mono">${I.num[r]}</td><td class="l">${C.bodies[rowBody[r]].name}</td><td class="l">${C.actions[Q.a[k]]}</td><td class="l hm">${STEPS[Q.step[k]]}</td>
            <td class="l hm" title="${C.tiers[Q.t[k]] || ''}">${tierShort(Q.t[k])}</td><td class="l">${Q.r[k] ? html`<span class="st review">[ ] review</span>` : 'ready'}</td>
            <td class="l mono">${Q.d[k] ? 'doc ' + Q.d[k] : Q.u[k] ? hostOf(Q.u[k]) : ''}</td></tr>${open === k ? html`<tr class="drawer"><td colspan="8"><div class="inner" id="qdrawer">Loading…</div></td></tr>` : ''}`; })}</tbody></table></div>
        ${pages > 1 ? html`<div class="pager"><button class="btn" type="button" data-p="${page - 1}" ${page === 0 ? raw('disabled') : ''}>← Previous</button>
          <span>page ${page + 1} of ${pages}</span><button class="btn" type="button" data-p="${page + 1}" ${page >= pages - 1 ? raw('disabled') : ''}>Next →</button></div>` : ''}`);
      const upd = (patch) => { Object.assign(st, patch); page = 0; open = null; setQuery(st); render(); $('#qfilters').classList.add('shown'); };
      $('#qf').addEventListener('click', () => { const f = $('#qfilters'); f.classList.toggle('shown'); $('#qf').setAttribute('aria-expanded', String(f.classList.contains('shown'))); });
      $$('.seg', box).forEach((s) => s.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) upd({ [s.dataset.k]: b.dataset.v }); }));
      $('#qb').addEventListener('change', (e) => upd({ b: e.target.value }));
      $('#qt').addEventListener('change', (e) => upd({ t: e.target.value }));
      $('#qall').addEventListener('click', () => { list.forEach((k) => selected.add(k)); render(); });
      $('#qnone').addEventListener('click', () => { selected.clear(); render(); });
      $('#qcsv').addEventListener('click', exportCSV);
      $('#qsql').addEventListener('click', () => exportSQL(selBern));
      $$('[data-p]', box).forEach((x) => x.addEventListener('click', () => { page = Number(x.dataset.p); open = null; render(); $('#qtable').scrollIntoView(); }));
      $$('#qtable input[type="checkbox"]').forEach((cb) => {
        cb.addEventListener('click', (e) => e.stopPropagation());
        cb.addEventListener('change', () => { const k = Number(cb.dataset.k); if (cb.checked) selected.add(k); else selected.delete(k); render(); const again = $('#qtable input[data-k="' + k + '"]'); if (again) again.focus(); });
      });
      $$('#qtable tr.go').forEach((tr) => {
        const toggle = () => { const k = Number(tr.dataset.k); open = open === k ? null : k; render(); const again = $('#qtable tr.go[data-k="' + k + '"]'); if (again) again.focus(); };
        tr.addEventListener('click', toggle);
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || (e.key === 'Escape' && open != null)) toggle(); if (e.key === ' ') { e.preventDefault(); const cb = $('input', tr); cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); } });
      });
      if (open != null) drawer(open);
    }
    const hostOf = (u) => { try { return new URL(u).host; } catch (e) { return u; } };
    async function drawer(k) {
      const r = Q.i[k];
      const d = await detailRow(r);
      const el = $('#qdrawer');
      if (!el) return;
      const title = d.tde || d.tfr || d.tit || '(no title in OPD)';
      const f = d.fix || {};
      el.innerHTML = String(html`<p><b>${title}</b></p>
        <table class="facts mono"><tbody>
          ${f.d ? html`<tr><th scope="row">OPD document</th><td>${f.d}</td></tr>` : ''}
          ${f.u ? html`<tr><th scope="row">Source document</th><td><a href="${f.u}" title="${f.u}">${f.u.length > 90 ? f.u.slice(0, 60) + '…' + f.u.slice(-24) : f.u}</a></td></tr>` : ''}
          <tr><th scope="row">Check</th><td>${Detail.tierText(f.t)}</td></tr>
          ${f.dt ? html`<tr><th scope="row">Document date</th><td>${ddmmyyyy(f.dt)}${f.ev ? ' · OPD answer events ' + f.ev.split(/\s+/).map(ddmmyyyy).join(' · ') : ''}</td></tr>` : ''}
          ${f.rr ? html`<tr><th scope="row">Review</th><td>${f.rr}</td></tr>` : ''}
          ${f.f ? html`<tr><th scope="row">Listed in</th><td><a href="${docLink(f.f)}">${f.f.split('/').pop()}</a></td></tr>` : ''}
        </tbody></table>${f.q ? html`<div class="quote">“${f.q}”</div>` : ''}
        <p class="links"><a href="#/affair/${I.id[r]}">Open in Lookup</a><a href="${C.opd_affair.replace('{id}', I.id[r])}">OpenParlData affair</a></p>`);
    }
    function exportCSV() {
      const rows = [['affair_id', 'number', 'body', 'parliament', 'action', 'step', 'source', 'check', 'status', 'needs_hash_decision', 'in_bern_plan', 'opd_doc_id', 'target_url', 'opd_url']];
      Array.from(selected).sort((a, b) => a - b).forEach((k) => {
        const r = Q.i[k];
        const b = C.bodies[rowBody[r]];
        rows.push([I.id[r], I.num[r], b.key, b.name, C.actions[Q.a[k]], Q.step[k], Q.s[k], Q.t[k], Q.r[k] ? 'review' : 'ready', Q.h[k] ? 'yes' : 'no',
          Q.p[k] ? 'yes' : 'no', Q.d[k], Q.u[k], C.opd_affair.replace('{id}', I.id[r])]);
      });
      download('gegenprobe_repairs_' + selected.size + '.csv', csv(rows), 'text/csv;charset=utf-8');
    }
    async function exportSQL(ks) {
      const btn = $('#qsql');
      btn.disabled = true;
      btn.textContent = 'Reading the plan…';
      let plan;
      try { plan = await getText(C.bern_plan); } catch (e) { toast('Could not read the plan'); render(); return; }
      const want = new Set(ks.map((k) => I.id[Q.i[k]]));
      const review = Array.from(selected).filter((k) => Q.s[k] === 'be' && C.actions[Q.a[k]] === 'relink' && Q.p[k] !== 1).map((k) => I.id[Q.i[k]]);
      const lines = plan.split('\n');
      const total = (plan.match(/expected_rows_changed: (\d+)/) || [])[1];
      const picked = [];
      const missing = new Set(want);
      for (const line of lines) {
        const m = line.match(/^WITH u AS \(UPDATE docs SET parent_type = 'affair', affair_id = (\d+),/);
        if (m && want.has(Number(m[1]))) { picked.push(line); missing.delete(Number(m[1])); }
      }
      const head = lines.findIndex((l) => l.startsWith('BEGIN;'));
      const tableLine = lines.find((l) => l.startsWith('CREATE TEMP TABLE gp_apply_be_changed'));
      const doAt = lines.findIndex((l) => l.startsWith('DO $$'));
      const tail = lines.slice(doAt).join('\n').split(total).join(String(picked.length));
      const out = [
        '-- Subset of apply_BE_plan.sql.txt (Gegenprobe dry-run plan for Bern): ' + picked.length + ' of ' + total + ' guarded statements,',
        '-- the selected relinks, copied verbatim; the closing guard expects exactly ' + picked.length + ' changed rows (all or nothing).',
        '-- Not executed by Gegenprobe. Relinks change the document hash and URL unless OPD keeps the old identifier (hash decision).',
        review.length ? '-- Selected but not in the plan (review rows, check before applying): ' + review.join(', ') : '-- Every selected Bern relink is in the plan.',
        missing.size ? '-- Not found in the plan: ' + Array.from(missing).join(', ') : '-- Every exported statement was found in the plan.',
        '-- Run as one script, e.g. psql -v ON_ERROR_STOP=1 -f <this file>',
        lines[head], tableLine,
      ].concat(picked).concat([tail]).join('\n');
      download('apply_BE_relink_subset_' + picked.length + '.sql.txt', out.endsWith('\n') ? out : out + '\n');
      toast(picked.length + ' guarded statements exported');
      render();
    }
    return { show };
  })();

  // ------------------------------------------------------------------------------------------ About
  const About = (() => {
    let done = false;
    function show() {
      if (done) return;
      done = true;
      const bd = C.bound;
      const grid = C.fields;
      const vlabel = { roles: 'needs roles', body: 'body-specific', untested: 'untested' };
      const groups = {};
      C.downloads.forEach((d) => { (groups[d.g] = groups[d.g] || []).push(d); });
      const kb = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' kB');
      $('#v-about').innerHTML = String(html`<div class="about" data-claims="about">
        <h1>About</h1>
        <div class="figs two wide"><div title="${bd.share_today} with answer text today, ${bd.share_after} once the ${fmt(bd.repaired)} repairs are applied"><span class="big">${bd.share_today}<span class="to">→</span><span class="red">${bd.share_after}</span></span>
          <span class="lbl">answer text attached: today → after the repairs</span></div>
          <div><span class="big">${fmt(bd.repaired)}</span><span class="lbl">repairs, keyed on OPD ids, no model</span></div></div>
        <dl class="form">
          <dt>Scope</dt><dd><b>${fmt(bd.written)}</b> interventions with a recorded government answer · OpenParlData (OPD)</dd>
          <dt>Check</dt><dd>answer text attached? if not, where it is and which repair</dd>
          <dt>Schema</dt><dd>one schema, if each field names its value’s role · <b>${bd.fields}</b> fields · <b>${bd.need_roles}</b> need roles · <b>${bd.body_specific}</b> body-specific · <b>${bd.untested}</b> untested</dd>
          <dt>Provenance</dt><dd>document · page · character span · route (rule, metadata, model) · a missing value is a typed gap</dd>
          <dt>Apertus</dt><dd>opt-in; a reviewer confirms each value it proposes · the repairs use no model</dd>
        </dl>
        <div class="page-body">
        <section class="sec"><h2>Schema fields</h2><div class="w">
          <div class="fgrid">${grid.map((f) => html`<div class="${f.verdict}" title="${f.why}"><div class="fn">${f.name}</div><div class="fv">${vlabel[f.verdict]}${f.fragile ? ' · fragile' : ''}${f.test ? ' · ' + f.test : ''}</div></div>`)}</div>
        </div></section>
        <section class="sec"><h2>Apertus, registered tests</h2><div class="w">
          <div class="recwrap"><table class="results"><tbody>
            <tr><td class="n">${bd.p2_pointer[0]}/${bd.p2_pointer[1]}</td><td>answer dates in ${bd.p2_parliaments} parliaments without rules (rules: ${bd.p2_rules[0]}/${bd.p2_rules[1]})</td><td class="src">P2</td></tr>
            <tr><td class="n">+${bd.p10_points}</td><td>points author-role recall in ${bd.p10_parliaments} parliaments without rules; precision not worse</td><td class="src">P10</td></tr>
            <tr><td class="n">${bd.p7[0]}/${bd.p7[1]}</td><td>sampled review-queue promotions are the government’s answer</td><td class="src">P7</td></tr>
          </tbody></table></div>
        </div></section>
        <section class="sec"><h2>Read more</h2><div class="w">
          <div class="linkrow"><a class="btn" href="${C.repo}">Repository</a><a class="btn" href="${C.links.report}">Technical report (PDF)</a><a class="btn" href="${C.links.decision_en}">Decision page</a><a class="btn" href="${C.links.decision_de}">Entscheidungsseite (DE)</a></div>
          <p class="hint">Track 2A · OpenParlData · Team 444</p>
        </div></section>
        <section class="sec"><h2>Downloads</h2><div class="w" data-meta="files">${Object.entries(groups).map(([g, fs]) => html`<details class="dl"><summary>${g} <span class="muted">(${fs.length})</span></summary><ul>
          ${fs.map((d) => html`<li><a class="fn" href="${d.h}">${d.f}</a><span class="w">${d.w}</span><span class="sz">${d.r != null ? fmt(d.r) + ' rows · ' : ''}${kb(d.b)}</span></li>`)}</ul></details>`)}</div></section>
        </div>
      </div>`);
    }
    return { show };
  })();

  // ------------------------------------------------------------------------------------------ theme + start
  function theme() {
    const btn = $('#theme');
    const order = ['auto', 'light', 'dark'];
    let t = store.get('gp-theme') || 'auto';
    const apply = () => {
      if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
      btn.textContent = t;
      btn.setAttribute('aria-label', 'Colour theme: ' + t);
    };
    apply();
    btn.addEventListener('click', () => { t = order[(order.indexOf(t) + 1) % order.length]; store.set('gp-theme', t); apply(); });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) {
      e.preventDefault();
      if (!location.hash.startsWith('#/affair') && location.hash !== '' && location.hash !== '#/' && !location.hash.startsWith('#/?')) location.hash = '#/';
      setTimeout(() => $('#q').focus(), 0);
    }
  });

  window.addEventListener('DOMContentLoaded', async () => {
    theme();
    try {
      await boot();
    } catch (e) {
      $('#loading').textContent = 'Could not load the data (' + e.message + '). Serve this folder over HTTP, e.g. python -m http.server.';
      return;
    }
    $('#loading').hidden = true;
    Lookup.init();
    window.addEventListener('hashchange', route);
    route();
  });
})();
