/* Gegenprobe app: Lookup | Parliaments | Repair queue | About. Static data under data/ (gegenprobe.app.build).
   Vanilla JS, no dependency, no third-party request. Every number outside the per-affair data comes from
   core.bound (bound to its claim by claims_app.json). Routes: #/ #/affair/<id> #/parliaments #/parliament/<key>
   #/queue #/about (query strings after "?"). Every view is the register's shell: a ruled list on the left (filters,
   group headers with counts), the selected item on the right (what, where, numbered actions, evidence).
   Keys: j/k move in the list, Enter opens, / search, 1-4 the item's numbered actions, Esc back. */
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
  const share = (k, n) => (n ? (100 * k / n).toFixed(1) + '%' : '—');
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
  const hostOf = (u) => { try { return new URL(u).host; } catch (e) { return u; } };
  const shortUrl = (u) => {
    try { const x = new URL(u); const p = x.pathname + x.search; return x.host + (p.length > 40 ? p.slice(0, 16) + '…' + p.slice(-20) : p); } catch (e) { return u; }
  };
  const mobile = () => window.matchMedia('(max-width: 900px)').matches;
  const sep = raw('<span class="sep">·</span>');

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
  let ORDER = null;        // every row, newest year first (the list without a query)
  let YEARS = [];          // the years present, newest first
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
    ORDER = Array.from({ length: n }, (_, r) => r).sort((a, b) => (yr[b] - yr[a]) || (a - b));
    YEARS = Array.from(new Set(yr)).sort((a, b) => b - a);
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
  async function fillTitles(box, rows) {
    await titlesFor(rows);
    $$('.pending[data-row]', box).forEach((el) => {
      const t = titleNow(Number(el.dataset.row));
      if (t != null) { el.textContent = t || '(no title in OPD)'; el.classList.remove('pending'); }
    });
  }

  // ------------------------------------------------------------------------------------------ vocabulary
  const HASH_LINE = 'OPD’s document hash is sha256(body key + parent type + URL): a relink changes the hash and the files.openparldata.ch address. OPD decides whether a relinked document keeps its old identifier; the dry-run plan writes the new one.';
  const TIER = { agenda_join: 'agenda join', be_verified: 'Bern: verified', be_review: 'Bern: check failed', be_fetch: 'Bern: verified',
    curia: 'Curia Vista', exact_doc_date: 'document date', exact_any_printed_date: 'printed date', date_window: 'date window',
    review: 'review', identity_wording_only: 'wording only' };
  const tierShort = (t) => TIER[t] || String(t || '').replace(/_/g, ' ');
  const tierText = (t) => (C.tiers[t] || t || '');
  // status code -> marker, the list's two lines, signal
  const ST = {
    a: { mk: '[x]', l: 'attached', kd: 'in OPD' },
    o: { mk: '[o]', l: 'oral', kd: 'no text expected' },
    R: { mk: '[→]', l: 'relink', kd: 'apply now' },
    B: { mk: '[→]', l: 'relink', kd: 'after hash decision' },
    b: { mk: '[ ]', l: 'relink · review', kd: 'check, then hash decision' },
    T: { mk: '[→]', l: 'tag', kd: 'apply now' },
    X: { mk: '[→]', l: 'extract', kd: 'apply now' },
    F: { mk: '[→]', l: 'fetch', kd: 'from the parliament' },
    f: { mk: '[ ]', l: 'fetch · review', kd: 'a person checks first' },
    V: { mk: '[ ]', l: 'candidate', kd: 'not counted' },
    I: { mk: '[!]', l: 'scan, no text', kd: 'no verified copy', sig: true },
    M: { mk: '[!]', l: 'not in OPD', kd: 'not found yet', sig: true },
    n: { mk: '[-]', l: 'record only', kd: 'no recorded answer' },
  };
  // one partition of the statuses, the same in Lookup and on a parliament's page
  const GROUPS = [
    ['repair', 'RBTXF', 'Missing · repair proposed'],
    ['review', 'bfV', 'Missing · review first'],
    ['nocopy', 'IM', 'Missing · no copy found'],
    ['oral', 'o', 'Oral · no text expected'],
    ['attached', 'a', 'Attached'],
    ['outside', 'n', 'Record only · no recorded answer'],
  ];
  const SHOW = { all: null, missing: 'RBTXFbfVIM', repair: 'RBTXF', review: 'bfV', nocopy: 'IM', oral: 'o', attached: 'a' };
  const SHOW_LABEL = { all: 'All, incl. outside the census', missing: 'Missing', repair: 'Repair proposed', review: 'Review first', nocopy: 'No copy found', oral: 'Oral', attached: 'Attached' };
  const STEPS = { now: 'Apply now', after_hash: 'After OPD’s hash decision (Bern)', fetch: 'Fetch from the parliaments' };
  const STEP_SHORT = { now: 'apply now', after_hash: 'after hash decision', fetch: 'fetch' };
  const docLink = (rel) => {
    if (!rel) return '';
    const name = rel.split('/').pop();
    const local = (C.downloads || []).find((d) => d.f === name);
    return local ? local.h : C.blob + rel;
  };
  const opdUrl = (id) => C.opd_affair.replace('{id}', id);
  const select = (id, label, opts, value, cls) => html`<div class="fl${cls ? ' ' + cls : ''}"><label class="k" for="${id}">${label}</label>
    <select id="${id}" class="${value ? 'on' : ''}">${opts.map(([v, l]) => html`<option value="${v}" ${String(v) === String(value) ? raw('selected') : ''}>${l}</option>`)}</select></div>`;
  const facts = (rows) => html`<dl class="facts">${rows.filter((x) => x && x[1] !== '' && x[1] != null).map(([k, v]) => html`<dt>${k}</dt><dd>${v}</dd>`)}</dl>`;
  const button = (key, label, attrs) => raw(`<${attrs.href ? 'a' : 'button'} class="box" data-key="${key}" ${attrs.href ? '' : 'type="button"'} ${Object.entries(attrs).filter(([, v]) => v != null && v !== false).map(([k, v]) => (v === true ? k : k + '="' + esc(v) + '"')).join(' ')}><span class="k">[${key}]</span> ${esc(label)}</${attrs.href ? 'a' : 'button'}>`);
  const crumb = (parts, back) => html`<p class="crumb">${back ? html`<a class="back" href="${back}">← back</a><span class="sep back">·</span>` : ''}${parts.map((p, i) => html`${i ? html`<span class="sep">›</span>` : ''}${p[1] ? html`<a href="${p[1]}">${p[0]}</a>` : p[0]}`)}</p>`;

  // where the answer is: one or two lines, the same in Lookup and in the repair queue
  function whereLines(code, d, id) {
    const f = d.fix || d.cand || {};
    const doc = f.d ? 'OPD document ' + f.d : '';
    switch (code) {
      case 'a': return [['Attached to this affair in OPD']];
      case 'o': return [['Answered orally in the sitting · no written text']];
      case 'R': return [[doc + ' · filed under an agenda item' + (f.n ? ' (' + f.n + ')' : '')], ['relink to affair ' + id + ' · apply now']];
      case 'B': return [[doc + ' · in OPD without a parent · named by the canton’s open data'], ['relink to affair ' + id + ' · after OPD’s hash decision']];
      case 'b': return [[doc + ' · in OPD without a parent · named by the canton’s open data'], ['relink to affair ' + id + ' · a person checks first, then the hash decision']];
      case 'T': return [[doc + ' · on this affair, under an unrecognised heading'], ['tag: set its category' + (f.c ? ' to ' + f.c : '') + ' · apply now']];
      case 'X': return [[doc + ' · a copy without usable text'], ['extract: store the verified text' + (f.ex ? ' (' + f.ex + ')' : '') + ' · apply now']];
      case 'F': case 'f': return [['Not in OPD · published by ' + (f.s === 'curia' ? 'the federal parliament (Curia Vista)' : f.u ? hostOf(f.u) : 'the parliament')],
        ['fetch: attach the parliament’s document to affair ' + id + (code === 'f' ? ' · a person checks first' : '')]];
      case 'V': return [['Candidate, not counted · ' + (f.d ? doc : f.u ? hostOf(f.u) : '')], ['nothing is applied until a person confirms it']];
      case 'I': return [['In OPD only as a scan without text · no verified copy yet', 'sig']];
      case 'M': return [['Not in OPD · ' + (d.flags & 4 ? 'a source adapter found nothing usable' : 'no list or source adapter has it yet'), 'sig']];
      default: return [['No recorded government answer · shown for its v0.2 record']];
    }
  }
  const whereHTML = (code, d, id) => html`<ul class="where">${whereLines(code, d, id).map(([t, c]) => html`<li class="${c || ''}">${t}</li>`)}</ul>`;

  function evidenceFacts(d) {
    const f = d.fix || d.cand;
    if (!f) return [];
    return [
      ['OPD document', f.d || ''],
      ['Source', f.u ? html`<a href="${f.u}" title="${f.u}">${shortUrl(f.u)}</a>` : ''],
      ['Title', f.x || ''],
      ['Check', f.t ? html`<span title="${tierText(f.t)}">${tierShort(f.t)}</span>` : ''],
      ['Decision', f.dn ? 'RRB ' + f.dn + (f.dt ? ' of ' + ddmmyyyy(f.dt) : '') : ''],
      ['Document date', !f.dn && f.dt ? ddmmyyyy(f.dt) : ''],
      ['OPD answer', f.ev ? f.ev.split(/\s+/).map(ddmmyyyy).join(' · ') : ''],
      ['Date match', f.m || ''],
      ['Category', f.c || ''],
      ['Listed in', f.f ? html`<a href="${docLink(f.f)}">${f.f.split('/').pop()}</a>` : ''],
    ];
  }
  function repairFacts(code, d, id, b) {
    const f = d.fix || d.cand;
    if (!f) return [];
    const step = { R: 'apply now', T: 'apply now', X: 'apply now', B: 'after OPD’s hash decision', b: 'after review + hash decision', F: 'fetch', f: 'after review' }[code];
    return [
      ['Action', code === 'V' ? 'none until confirmed' : (f.a || '')],
      ['Step', step || ''],
      ['Status', f.r || code === 'V' ? html`<span class="sig">[ ] review</span>` : 'ready'],
      ['Review', f.r || code === 'V' ? (f.rr || tierText(f.t)) : ''],
      ['Hash', f.h ? (f.p ? String(f.hb).slice(0, 10) + '… → ' + String(f.ha).slice(0, 10) + '…' : 'not in the dry-run plan') : ''],
      ['Plan', f.h && f.p ? html`<a href="${C.bern_plan}">apply_BE_plan.sql.txt</a>` : ''],
      ['Queue', code !== 'V' ? html`<a href="#/queue?b=${encodeURIComponent(b.key)}&amp;id=${id}">open in the repair queue</a>` : ''],
    ];
  }

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
  // numbers that differ from the query in one part (2023.RRGR.388 -> 2022.RRGR.388 ...)
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
    return out.sort((a, b) => (a[1] - b[1]) || (I.yr[b[0]] - I.yr[a[0]])).slice(0, 8).map((x) => x[0]);
  }

  // ------------------------------------------------------------------------------------------ router
  const VIEWS = ['lookup', 'parliaments', 'queue', 'about'];
  let view = 'lookup';
  function parse() {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, qs] = h.split('?');
    return { parts: path.split('/').filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(qs || '') };
  }
  function route() {
    const { parts, params } = parse();
    view = 'lookup';
    if (parts[0] === 'parliaments' || parts[0] === 'parliament') view = 'parliaments';
    else if (parts[0] === 'queue') view = 'queue';
    else if (parts[0] === 'about') view = 'about';
    VIEWS.forEach((v) => { $('#v-' + v).hidden = v !== view; });
    $$('.views a').forEach((a) => { if (a.dataset.view === view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    $('#xmenu').open = false;
    if (view === 'lookup') Lookup.show(parts[0] === 'affair' ? Number(parts[1]) : null, params);
    else if (view === 'parliaments') Parliaments.show(parts[0] === 'parliament' ? parts[1] : null, params);
    else if (view === 'queue') Queue.show(params);
    else About.show(params);
    const t = { lookup: 'Lookup', parliaments: 'Parliaments', queue: 'Repair queue', about: 'About' }[view];
    document.title = t + ' · Gegenprobe';
  }
  const qsOf = (params) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== '' && v != null && v !== false) qs.set(k, v); });
    const s = qs.toString();
    return s ? '?' + s : '';
  };
  const setQuery = (params) => {
    const [path] = location.hash.split('?');
    history.replaceState(null, '', (path || '#/') + qsOf(params));
  };
  const setOpen = (box, on) => { box.classList.toggle('open', !!on); };

  // ------------------------------------------------------------------------------------------ shell
  const Shell = (() => {
    function status() {
      const bd = C.bound;
      $('#c-lookup').textContent = fmt(bd.written);
      $('#c-parliaments').textContent = fmt(C.bodies.filter((b) => b.written > 0).length);
      $('#c-queue').textContent = fmt(bd.repaired);
      $('#ctxline').innerHTML = String(html`<span>OPD snapshot <b data-meta="date">${ddmmyyyy(C.snapshot)}</b></span>${sep}
        <span><b>${fmt(bd.written)}</b> interventions</span>${sep}
        <span title="${bd.share_today} with answer text today, ${bd.share_after} once the ${fmt(bd.repaired)} repairs are applied">answer text <b>${bd.share_today}</b> → <b>${bd.share_after}</b></span>${sep}
        <span><b>${fmt(bd.repaired)}</b> repairs</span>${sep}
        <span>build <b data-meta="hash">${C.build}</b></span><button class="qh" id="qh" type="button" aria-expanded="false" aria-controls="help">[?]</button>`);
      $('#help').innerHTML = String(html`<dt>OPD snapshot</dt><dd>OpenParlData’s metadata as scanned on ${ddmmyyyy(C.snapshot)}; every count here is from it</dd>
        <dt>Interventions</dt><dd>interpellations, motions, postulates and questions with a recorded government answer</dd>
        <dt>Answer text</dt><dd>share with the answer text attached in OPD: today → once every proposed repair is applied</dd>
        <dt>Repairs</dt><dd>relink, tag, extract, fetch; keyed on OPD ids, no model; steps: apply now · after OPD’s hash decision (Bern) · fetch</dd>
        <dt>Build</dt><dd>sha256 of this site’s code and data, first characters; two builds of one commit give the same hash</dd>`);
      $('#qh').addEventListener('click', () => {
        const h = $('#help');
        h.hidden = !h.hidden;
        $('#qh').setAttribute('aria-expanded', String(!h.hidden));
      });
    }
    function menu() {
      const dl = (f) => (C.downloads || []).find((d) => d.f === f);
      const kb = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' kB');
      const link = (f, label) => { const d = dl(f); return d ? html`<a href="${d.h}" download><span>${label}</span><span class="i2">${kb(d.b)}</span></a>` : ''; };
      $('#xmm').innerHTML = String(html`<button type="button" id="x-sel"><span>Repair queue · selection · CSV</span><span class="i2" id="x-seln"></span></button>
        <button type="button" id="x-all"><span>Repair queue · all rows · CSV</span><span class="i2">${fmt(C.bound.repaired)}</span></button>
        ${link('apply_BE_plan.sql.txt', 'Bern relink plan · SQL, dry run')}
        <hr>${link('interventions.tsv.gz', 'Interventions · TSV.gz')}${link('parliaments.csv', 'Parliaments · CSV')}
        ${link('444_Report.pdf', 'Technical report · PDF')}<hr><a href="#/about?s=downloads"><span>All downloads</span><span class="i2">→ About</span></a>`);
      $('#xmenu').addEventListener('toggle', () => { if ($('#xmenu').open) $('#x-seln').textContent = fmt(Queue.selectedCount()); });
      $('#x-sel').addEventListener('click', () => { $('#xmenu').open = false; Queue.exportSelection(); });
      $('#x-all').addEventListener('click', () => { $('#xmenu').open = false; Queue.exportAll(); });
      document.addEventListener('click', (e) => { if ($('#xmenu').open && !e.target.closest('#xmenu')) $('#xmenu').open = false; });
    }
    function theme() {
      const btn = $('#theme');
      const order = ['auto', 'light', 'dark'];
      let t = store.get('gp-theme') || 'auto';
      const apply = () => {
        if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
        btn.textContent = 'Theme: ' + t;
        btn.setAttribute('aria-label', 'Colour theme: ' + t);
      };
      apply();
      btn.addEventListener('click', () => { t = order[(order.indexOf(t) + 1) % order.length]; store.set('gp-theme', t); apply(); });
    }
    return { status, menu, theme };
  })();

  // a list's rows of affairs, grouped by status; `href(r)` gives each row's link
  function affairRow(r, href, selected) {
    const s = ST[I.st[r]] || ST.M;
    const b = C.bodies[rowBody[r]];
    const t = titleNow(r);
    return html`<tr class="it" data-href="${href}" aria-selected="${selected}"><td class="mk${s.sig ? ' sig' : ''}">${s.mk}</td>
      <td class="ti"><b><a class="${t == null ? 'pending' : ''}" data-row="${r}" href="${href}" tabindex="-1">${t == null ? '…' : (t || '(no title in OPD)')}</a></b>
      <span class="code">${I.num[r]} · ${b.name} · ${I.yr[r] || '—'}</span></td>
      <td class="aw">${s.l}<span class="kd">${s.kd}</span></td></tr>`;
  }
  const groupRow = (label, n, extra) => html`<tr class="grp"><td colspan="3">${label} · ${fmt(n)}${extra ? html`<span class="i2">${extra}</span>` : ''}</td></tr>`;
  const moreRow = (key, hidden) => html`<tr class="more"><td></td><td colspan="2"><button class="tb" type="button" data-more="${key}">[+] show ${fmt(Math.min(hidden, 100))} more</button> <span class="i2">· ${fmt(hidden)} not shown</span></td></tr>`;
  function wireList(tbody) {
    tbody.addEventListener('click', (e) => {
      if (e.target.closest('a,button,input')) return;
      const tr = e.target.closest('tr.it');
      if (tr) location.hash = tr.dataset.href;
    });
  }

  // ------------------------------------------------------------------------------------------ Lookup
  const Lookup = (() => {
    const st = { q: '', s: 'all', b: '', y: '', t: '' };
    let hits = [];
    let current = null;
    let seq = 0;
    let lim = {};
    let listKey = null;
    const LIM = 30;
    const box = () => $('#v-lookup');
    const listQS = () => qsOf({ q: st.q, s: st.s === 'all' ? '' : st.s, b: st.b, y: st.y, t: st.t });
    const hrefOf = (r) => '#/affair/' + I.id[r] + listQS();

    function init() {
      let timer = null;
      $('#q').addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(() => run($('#q').value), 160);
      });
      $('#q').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); const tr = $('#lk tr.it'); if (tr) location.hash = tr.dataset.href; }
        if (e.key === 'ArrowDown') { e.preventDefault(); $('#q').blur(); Keys.move(1); }
      });
      $('#lk-filters').addEventListener('change', (e) => {
        const k = { 'lk-s': 's', 'lk-b': 'b', 'lk-y': 'y', 'lk-t': 't' }[e.target.id];
        if (!k) return;
        st[k] = e.target.value;
        lim = {};
        setQuery(Object.fromEntries(new URLSearchParams(listQS())));
        renderList(true).then(() => { const el = $('#' + e.target.id); if (el) el.focus(); });
      });
      $('#lk tbody').addEventListener('click', (e) => {
        const m = e.target.closest('[data-more]');
        if (m) { lim[m.dataset.more] = (lim[m.dataset.more] || LIM) + 100; renderList(false); }
      });
      wireList($('#lk tbody'));
      $('#lk-case').addEventListener('click', (e) => {
        const ex = e.target.closest('[data-q]');
        if (ex) { e.preventDefault(); $('#q').value = ex.dataset.q; run(ex.dataset.q); }
      });
    }

    async function run(text) {
      st.q = text;
      const my = ++seq;
      const res = await search(text);
      if (my !== seq) return;
      hits = res;
      lim = {};
      titleWords = fold(text).split(/[^a-z0-9]+/).filter((w) => w.length >= 3 && !/^\d+$/.test(w));
      setQuery(Object.fromEntries(new URLSearchParams(listQS())));
      renderList(true);
    }

    function rowsNow() {
      const base = st.q.trim() ? hits : ORDER;
      const g = SHOW[st.s];
      const bi = st.b && B[st.b] ? B[st.b].i : -1;
      const y = st.y === '' ? -1 : Number(st.y);
      const t = st.t === '' ? -1 : Number(st.t);
      const out = [];
      const counts = {};
      for (const r of base) {
        if (bi >= 0 && rowBody[r] !== bi) continue;
        if (y >= 0 && I.yr[r] !== y) continue;
        if (t >= 0 && I.ty[r] !== t) continue;
        counts[I.st[r]] = (counts[I.st[r]] || 0) + 1;
        if (g && !g.includes(I.st[r])) continue;
        out.push(r);
      }
      return [out, counts];
    }

    function filters(counts) {
      const n = (codes) => (codes ? Array.from(codes).reduce((a, c) => a + (counts[c] || 0), 0) : Object.values(counts).reduce((a, b) => a + b, 0));
      const bodies = C.bodies.filter((b) => b.n > 0).slice().sort((a, b) => a.name.localeCompare(b.name));
      $('#lk-filters').innerHTML = String(html`
        ${select('lk-s', 'Show', Object.keys(SHOW).map((k) => [k, SHOW_LABEL[k] + ' ' + fmt(n(SHOW[k]))]), st.s === 'all' ? '' : st.s)}
        ${select('lk-b', 'Parliament', [['', 'All']].concat(bodies.map((b) => [b.key, b.name])), st.b)}
        ${select('lk-y', 'Year', [['', 'All']].concat(YEARS.map((y) => [y, y || 'unknown'])), st.y)}
        ${select('lk-t', 'Type', [['', 'All']].concat(C.types.slice(1).map((t, i) => [i + 1, t])), st.t)}`);
      $('#lk-s').value = st.s;
    }

    async function renderList(top) {
      const [list, counts] = rowsNow();
      filters(counts);
      const tb = $('#lk tbody');
      const at = current != null ? byId.get(current) : undefined;
      const parts = [];
      const shown = [];
      let pinned = at !== undefined;
      if (!list.length) {
        const near = st.q.trim() && st.s === 'all' ? nearNumbers(st.q) : [];
        parts.push(html`<tr class="none"><td></td><td colspan="2">No match${st.q.trim() ? html` for “${st.q}”` : ''}${st.s !== 'all' || st.b || st.y || st.t ? ' with these filters' : ''}.
          ${near.length ? html`<br>Close numbers: ${near.map((r, i) => html`${i ? ' · ' : ''}<a href="#/affair/${I.id[r]}">${I.num[r]}</a>`)}` : ''}</td></tr>`);
      }
      for (const [key, codes, label] of GROUPS) {
        const rows = list.filter((r) => codes.includes(I.st[r]));
        if (!rows.length) continue;
        const l = lim[key] || LIM;
        const page = rows.slice(0, l);
        if (pinned && page.includes(at)) pinned = false;
        parts.push(groupRow(label, rows.length));
        page.forEach((r) => { parts.push(affairRow(r, hrefOf(r), I.id[r] === current)); shown.push(r); });
        if (rows.length > l) parts.push(moreRow(key, rows.length - l));
      }
      if (pinned) {  // the open affair is not among the rows shown: it heads the list
        parts.unshift(groupRow('Open', 1), affairRow(at, hrefOf(at), true));
        shown.push(at);
      }
      tb.innerHTML = String(html`${parts}`);
      $('#lk-count').innerHTML = String(html`<span><b>${fmt(list.length)}</b> listed · ${fmt(shown.length)} shown</span><span class="keys">j/k · Enter · / search</span>`);
      if (top) $('#lk-wrap').scrollTop = 0;
      listKey = listQS();
      reveal();
      fillTitles(tb, shown);
    }
    function reveal() {
      const on = $('#lk tr.it[aria-selected="true"]');
      if (on) on.scrollIntoView({ block: 'nearest' });
    }

    let first = true;
    async function show(id, params) {
      const want = { q: params.get('q') || '', s: params.get('s') || 'all', b: params.get('b') || '', y: params.get('y') || '', t: params.get('t') || '' };
      current = id;
      setOpen(box(), id != null);
      const qChanged = want.q !== st.q || first;
      const changed = qChanged || ['s', 'b', 'y', 't'].some((k) => want[k] !== st[k]);
      Object.assign(st, want);
      if (qChanged) { $('#q').value = st.q; first = false; await run(st.q); } else if (changed || listKey == null) { lim = {}; await renderList(true); } else {
        $$('#lk tr.it').forEach((tr) => tr.setAttribute('aria-selected', String(tr.dataset.href.startsWith('#/affair/' + id + '?') || tr.dataset.href === '#/affair/' + id)));
        if (id != null && !$('#lk tr.it[aria-selected="true"]')) await renderList(false); else reveal();
      }
      renderCase(id);
    }

    function summary() {
      const bd = C.bound;
      return html`${crumb([['Lookup']])}<h2>Answer texts in OpenParlData</h2>
        <p class="ref">Select an affair on the left, or search: number, title words, OPD id, parliament</p>
        <div class="sec" data-claims="lookup"><dl class="facts wide">
          <dt>Scope</dt><dd><b>${fmt(bd.written)}</b> interventions with a recorded government answer</dd>
          <dt>Today</dt><dd><b>${bd.share_today}</b> with the answer text attached in OPD</dd>
          <dt>After repairs</dt><dd><b>${bd.share_after}</b> once the <b>${fmt(bd.repaired)}</b> proposed repairs are applied</dd>
          <dt>Steps</dt><dd>${fmt(bd.now)} apply now · ${fmt(bd.after_hash)} after OPD’s hash decision (Bern) · ${fmt(bd.fetch)} fetch from the parliaments</dd>
          <dt>Try</dt><dd><a href="#" data-q="2021.RRGR.388">2021.RRGR.388</a> · <a href="#" data-q="Bern 39369">Bern 39369</a> · <a href="#" data-q="Grundwasser">Grundwasser</a> · <a href="#" data-q="Lugano">Lugano</a></dd>
        </dl></div>`;
    }

    async function renderCase(id) {
      const el = $('#lk-case');
      if (id == null) { el.innerHTML = String(summary()); return; }
      const r = byId.get(id);
      const back = '#/' + listQS();
      if (r === undefined) {
        el.innerHTML = String(html`${crumb([['Lookup', back], ['OPD ' + id]], back)}<h2>Not in the census</h2>
          <p class="ref">OPD id ${id} is not among the interventions with a recorded government answer</p>
          <div class="btns">${button(1, 'Open in OPD', { href: opdUrl(id) })}</div>`);
        return;
      }
      el.innerHTML = String(html`${crumb([['Lookup', back], [I.num[r]]], back)}<p class="ref">Loading…</p>`);
      const d = await detailRow(r);
      if (current !== id) return;
      el.innerHTML = String(Affair.render(r, d, back));
      Affair.wire(el, r, d);
    }
    const focusSearch = () => { $('#q').focus(); $('#q').select(); };
    return { init, show, focusSearch };
  })();

  // ------------------------------------------------------------------------------------------ Affair (one intervention)
  const Affair = (() => {
    function render(r, d, back) {
      const b = C.bodies[rowBody[r]];
      const code = I.st[r];
      const s = ST[code] || ST.M;
      const id = I.id[r];
      const titles = [['DE', d.tde], ['FR', d.tfr], ['IT', d.tit]].filter((x) => x[1]);
      const main = titles[0];
      const head = {
        a: 'Attached in OPD', o: 'Oral answer · no written text expected', R: 'Missing in OPD · repair proposed: relink · apply now',
        B: 'Missing in OPD · repair proposed: relink · after OPD’s hash decision', b: 'Missing in OPD · relink after review and the hash decision',
        T: 'Missing in OPD · repair proposed: tag · apply now', X: 'Missing in OPD · repair proposed: extract · apply now',
        F: 'Missing in OPD · repair proposed: fetch from the parliament', f: 'Missing in OPD · fetch after review',
        V: 'Missing in OPD · a candidate for review, not counted', I: 'Missing in OPD · scan without text, no verified copy',
        M: 'Missing in OPD · no copy found yet', n: 'No recorded government answer · record only',
      }[code];
      const affair = [
        ['Parliament', html`<a href="#/parliament/${b.key}">${b.name}</a>`],
        ['Type', (C.types[I.ty[r]] || '') + (d.typeRaw && d.typeRaw !== C.types[I.ty[r]] ? ' (' + d.typeRaw + ')' : '')],
        ['Submitted', d.flags & 1 ? html`<span title="OPD’s begin date is its load timestamp">unknown</span>` : d.subSrc === 'begin_date' ? html`<span title="OPD begin date">${ddmmyyyy(d.sub)}</span>` : ddmmyyyy(d.sub)],
        ['Answered', ddmmyyyy(d.ans)],
        ['Link', d.link ? d.link.replace(/_/g, ' ') : ''],
        ['Date trust', b.date_trust ? b.date_trust.replace(/_/g, ' ') : ''],
      ];
      const ev = evidenceFacts(d);
      const rp = repairFacts(code, d, id, b);
      const cols = [['Affair', affair]].concat(ev.length ? [['Evidence', ev]] : []).concat(rp.length ? [[code === 'V' ? 'Review' : 'Repair', rp]] : []);
      const f = d.fix || d.cand || {};
      return html`${crumb([['Lookup', back], [b.name, '#/?b=' + encodeURIComponent(b.key)], [String(I.yr[r] || '—')], [I.num[r]]], back)}
        <h2>${main ? main[1] : '(no title in OPD)'}</h2>
        ${titles.slice(1).map(([lg, t]) => html`<p class="alt"><span class="lg">${lg}</span>${t}</p>`)}
        <p class="ref"><b>${I.num[r]}</b> · OPD ${id} · ${b.key} · ${C.types[I.ty[r]] || ''} · ${I.yr[r] || 'year unknown'}</p>
        <p class="state${s.sig ? ' sig' : ''}">${s.mk} ${head}</p>
        <div class="sec"><p class="sl">Where the answer is</p>${whereHTML(code, d, id)}
          <div class="btns">${button(1, 'Open in OPD', { href: opdUrl(id), rel: 'noopener' })}${button(2, 'Parliament page', d.url ? { href: d.url, rel: 'noopener' } : { disabled: true, title: 'OPD holds no link to the parliament’s page' })}
          ${button(3, 'Copy link', { 'data-copy': '#/affair/' + id })}${button(4, 'v0.2 record (JSON)', d.flags & 2 ? { href: 'data/r/' + id + '.json', download: 'gegenprobe_record_' + id + '.json', title: 'The record’s cells: field, value, role, page, character span, route' } : { disabled: true, title: 'No v0.2 record for this affair' })}</div></div>
        <div class="sec"><div class="ftg">${cols.map(([h, rows]) => html`<div class="ftc"><p class="lh">${h}</p>${facts(rows)}</div>`)}</div>
          ${f.q ? html`<p class="quote">“${f.q}”</p>` : ''}</div>
        <div id="record"></div>
        <details class="more2"><summary>Details</summary><dl class="facts">
          <dt>Status</dt><dd>${head}</dd>
          ${f.t ? html`<dt>Check</dt><dd>${tierText(f.t)}</dd>` : ''}
          ${f.h ? html`<dt>Hash decision</dt><dd>${HASH_LINE}</dd>` : ''}
          <dt>Date trust</dt><dd>how far OPD’s answer dates for this parliament can be trusted (census/date_trust.json)</dd>
          <dt>Link</dt><dd>how the answer document hangs in OPD: attached, under an agenda item, without a parent, scan, oral, absent</dd></dl></details>`;
    }
    function wire(box, r, d) {
      $$('[data-copy]', box).forEach((btn) => btn.addEventListener('click', () => {
        const url = location.origin + location.pathname + btn.dataset.copy;
        (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => toast('Link copied: ' + btn.dataset.copy),
          () => { history.replaceState(null, '', btn.dataset.copy); toast('Link in the address bar'); });
      }));
      if (d.flags & 2) Record.load($('#record', box), I.id[r]);
    }
    return { render, wire };
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
          return html`<tr data-i="${i}" class="${c.bb ? 'loc' : ''}" tabindex="${c.bb ? 0 : -1}"><td>${label(c.p, c)}</td><td class="v">${c.v}${c.q ? html`<span class="q">“${c.q}”</span>` : ''}${how ? html`<span class="how">${how}</span>` : ''}</td>
            <td>${(c.role || '').replace(/_/g, ' ')}</td><td>${where(c)}</td><td>${c.rt}</td></tr>`;
        }
        return html`<tr data-i="${i}"><td>${label(c.p, c)}</td><td class="v"><span class="gap" title="${c.e || ''}">[–] ${GAP[c.nr] || (c.nr || '').replace(/_/g, ' ')}</span></td>
          <td>${(c.role || '').replace(/_/g, ' ')}</td><td></td><td>${c.rt || ''}</td></tr>`;
      };
      const idx = new Map(rec.cells.map((c, i) => [c, i]));
      const table = (cells) => html`<div class="tblw"><table class="rec"><thead><tr><th>Field</th><th title="A value, or a typed gap [–] with its reason">Value</th><th>Role</th><th title="Page · character span">Where</th><th>Route</th></tr></thead>
        <tbody>${cells.map((c) => row(c, idx.get(c)))}</tbody></table></div>`;
      const pages = new Map();
      rec.cells.forEach((c, i) => {
        if (!c.bb) return;
        const key = c.doc + '#' + c.bpg;
        if (!pages.has(key)) pages.set(key, []);
        c.bb.forEach((b) => pages.get(key).push([i, b]));
      });
      const outline = (key, boxes) => {
        const [w, hgt] = rec.pages[key] || [595, 842];
        const lines = [];
        const margin = Math.round(w / 12);
        for (let y = margin * 1.2; y < hgt - margin; y += margin * 0.44) lines.push(html`<line x1="${margin}" x2="${w - margin}" y1="${y}" y2="${y}"></line>`);
        return html`<div class="page"><svg viewBox="0 0 ${w} ${hgt}" role="img" aria-label="Page outline with the located values">${lines}
          ${boxes.map(([i, b]) => html`<rect class="b" data-i="${i}" x="${b[0]}" y="${b[1]}" width="${Math.max(b[2] - b[0], 4)}" height="${Math.max(b[3] - b[1], 4)}"></rect>`)}</svg>
          <div class="pl">${key.replace('#', ' · p. ')}</div></div>`;
      };
      const located = rec.cells.filter((c) => c.k === 'v').length;
      const gaps = rec.cells.length - located;
      box.innerHTML = String(html`<div class="sec"><p class="sl">Record v0.2<span class="sp">${fmt(located)} values · ${fmt(gaps)} typed gaps</span></p>
        <p class="ref">${rec.label} · schema ${rec.v} · ${rec.docs.map((d, k) => html`${k ? ' · ' : ''}<a href="${d.url}">${d.id}</a> ${d.role}${d.n ? ' ' + d.n + ' p.' : ''}`)}</p>
        ${pages.size ? html`<div class="pages">${Array.from(pages.entries()).map(([k, b]) => outline(k, b))}</div>` : ''}
        ${table(main)}
        ${qa.length ? html`<details><summary>Question–answer pairs · ${fmt(qa.length)}</summary>${table(qa)}</details>` : ''}</div>`);
      const on = (i, v) => { $$('[data-i="' + i + '"]', box).forEach((el) => el.classList.toggle('on', v)); };
      box.addEventListener('mouseover', (e) => { const t = e.target.closest('[data-i]'); if (t) on(t.dataset.i, true); });
      box.addEventListener('mouseout', (e) => { const t = e.target.closest('[data-i]'); if (t) on(t.dataset.i, false); });
      box.addEventListener('focusin', (e) => { const t = e.target.closest('tr[data-i]'); if (t) on(t.dataset.i, true); });
      box.addEventListener('focusout', (e) => { const t = e.target.closest('tr[data-i]'); if (t) on(t.dataset.i, false); });
    }
    return { load };
  })();

  // ------------------------------------------------------------------------------------------ Parliaments
  const LEVELS = { all: null, cantons: ['canton'], communes: ['city', 'municipality'], federal: ['federal', 'country'] };
  const Parliaments = (() => {
    const SORTS = { gap: 'gap', after: 'after repairs', today: 'today', repaired: 'repairs', written: 'answers', name: 'name' };
    const val = (b, k) => ({
      today: b.written ? b.attached / b.written : 0, after: b.written ? (b.attached + b.repaired) / b.written : 0,
    }[k] ?? b[k]);
    let st = { level: 'all', lang: 'all', sort: 'gap', dir: 'desc', text: '' };
    let key = null;
    let det = { f: 'missing', p: 0 };
    let listKey = null;
    const PAGE = 100;
    const listQS = () => qsOf({ level: st.level === 'all' ? '' : st.level, lang: st.lang === 'all' ? '' : st.lang,
      sort: st.sort === 'gap' ? '' : st.sort, dir: st.dir === (st.sort === 'name' ? 'asc' : 'desc') ? '' : st.dir, text: st.text });

    function init() {
      $('#pl-filters').addEventListener('change', (e) => {
        const k = { 'pl-level': 'level', 'pl-lang': 'lang', 'pl-sort': 'sort' }[e.target.id];
        if (!k) return;
        st[k] = e.target.value;
        if (k === 'sort') st.dir = st.sort === 'name' ? 'asc' : 'desc';
        upd();
        const el = $('#' + e.target.id);
        if (el) el.focus();
      });
      $('#pl-filters').addEventListener('input', (e) => { if (e.target.id === 'pl-text') { st.text = e.target.value; upd(true); } });
      $('#pl thead').addEventListener('click', (e) => {
        const b = e.target.closest('[data-sort]');
        if (!b) return;
        const k = b.dataset.sort;
        if (st.sort === k) st.dir = st.dir === 'asc' ? 'desc' : 'asc'; else { st.sort = k; st.dir = k === 'name' ? 'asc' : 'desc'; }
        upd();
      });
      wireList($('#pl tbody'));
    }
    function upd(keepFocus) {
      const path = key ? '#/parliament/' + encodeURIComponent(key) : '#/parliaments';
      history.replaceState(null, '', path + listQS());
      renderList(keepFocus);
      if (!key) renderCase((rows()[0] || {}).key);
    }
    function rows() {
      const lv = LEVELS[st.level];
      const t = fold(st.text);
      const list = C.bodies.filter((b) => b.written > 0 && (!lv || lv.includes(b.level)) && (st.lang === 'all' || b.lang === st.lang)
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
    function renderList(keepFocus) {
      const list = rows();
      const langs = Array.from(new Set(C.bodies.filter((b) => b.written > 0).map((b) => b.lang).filter(Boolean))).sort();
      if (!keepFocus) {
        $('#pl-filters').innerHTML = String(html`
          ${select('pl-level', 'Level', Object.keys(LEVELS).map((l) => [l, l === 'all' ? 'All' : l]), st.level === 'all' ? '' : st.level)}
          ${select('pl-lang', 'Language', [['all', 'All']].concat(langs.map((l) => [l, l])), st.lang === 'all' ? '' : st.lang)}
          ${select('pl-sort', 'Sort', Object.entries(SORTS).map(([k, l]) => [k, l + (k === 'name' ? ' ↑' : ' ↓')]), st.sort === 'gap' ? '' : st.sort)}
          <div class="fl"><label class="k" for="pl-text">Name</label><input id="pl-text" type="text" value="${st.text}" placeholder="filter" autocomplete="off"></div>`);
        $('#pl-level').value = st.level;
        $('#pl-lang').value = st.lang;
        $('#pl-sort').value = st.sort;
      }
      const sortTh = (k, label, cls) => html`<th class="${cls || ''}" ${st.sort === k ? raw('aria-sort="' + (st.dir === 'asc' ? 'ascending' : 'descending') + '"') : ''}><button type="button" data-sort="${k}">${label}${st.sort === k ? (st.dir === 'asc' ? ' ↑' : ' ↓') : ''}</button></th>`;
      $('#pl thead tr').innerHTML = String(html`${sortTh('name', 'Parliament')}${sortTh('after', 'Today → after')}${sortTh('gap', 'Gap', 'r')}`);
      const sel = key || (list[0] && list[0].key);
      $('#pl tbody').innerHTML = String(html`${list.length ? list.map((b) => html`<tr class="it" data-href="#/parliament/${b.key}${listQS()}" data-key="${b.key}" aria-selected="${b.key === sel}">
        <td class="ti"><b><a href="#/parliament/${b.key}${listQS()}" tabindex="-1">${b.name}</a></b><span class="code">${b.key} · ${b.level} · ${b.lang || '—'}</span></td>
        <td class="aw">${share(b.attached, b.written)} → ${share(b.attached + b.repaired, b.written)}<span class="kd">${fmt(b.repaired)} repairs</span></td>
        <td class="aw r">${fmt(b.gap)}<span class="kd">${fmt(b.open)} open</span></td></tr>`) : html`<tr class="none"><td colspan="3">No parliament with these filters.</td></tr>`}`);
      const tot = list.reduce((a, b) => [a[0] + b.written, a[1] + b.attached, a[2] + b.repaired], [0, 0, 0]);
      $('#pl-count').innerHTML = String(html`<span><b>${fmt(list.length)}</b> parliaments · ${fmt(tot[0])} answers · ${share(tot[1], tot[0])} → ${share(tot[1] + tot[2], tot[0])}</span><span class="keys">j/k · Enter</span>`);
      listKey = listQS();
      const on = $('#pl tr.it[aria-selected="true"]');
      if (on) on.scrollIntoView({ block: 'nearest' });
    }
    function show(k, params) {
      const want = { level: params.get('level') || 'all', lang: (params.get('lang') || 'all').replace(/^(?!all$)(.*)$/, (m) => m.toUpperCase()),
        sort: params.get('sort') || 'gap', dir: params.get('dir') || '', text: params.get('text') || '' };
      if (!want.dir) want.dir = want.sort === 'name' ? 'asc' : 'desc';
      const keyChanged = k !== key;
      key = k || null;
      det = { f: params.get('f') || 'missing', p: Number(params.get('p') || 0) };
      setOpen($('#v-parliaments'), !!key);
      const changed = Object.keys(want).some((x) => want[x] !== st[x]) || listKey == null;
      st = want;
      if (changed || keyChanged) renderList();
      renderCase(key || (rows()[0] || {}).key);
    }
    async function renderCase(k) {
      const el = $('#pl-case');
      const b = B[k];
      el.dataset.key = k || '';
      const back = '#/parliaments' + listQS();
      if (!b) { el.innerHTML = String(html`${crumb([['Parliaments', back]], back)}<p class="empty">No parliament with key ${k || ''}.</p>`); return; }
      const g = SHOW[det.f] || null;
      const list = [];
      const counts = {};
      for (let r = b.start; r < b.start + b.n; r++) {
        if (I.st[r] === 'n') continue;
        counts[I.st[r]] = (counts[I.st[r]] || 0) + 1;
        if (!g || g.includes(I.st[r])) list.push(r);
      }
      const nOf = (codes) => (codes ? Array.from(codes).reduce((a, c) => a + (counts[c] || 0), 0) : Object.values(counts).reduce((a, x) => a + x, 0));
      const pages = Math.max(1, Math.ceil(list.length / PAGE));
      det.p = Math.min(det.p, pages - 1);
      const slice = list.slice(det.p * PAGE, det.p * PAGE + PAGE);
      const c = b.by_code || {};
      const act = [['relink', (c.R || 0), (c.B || 0) + (c.b || 0), 0], ['tag', c.T || 0, 0, 0], ['extract', c.X || 0, 0, 0], ['fetch', 0, 0, (c.F || 0) + (c.f || 0)]]
        .filter((x) => x[1] + x[2] + x[3] > 0);
      const step = b.by_step || {};
      const selfQS = (f, p) => '#/parliament/' + encodeURIComponent(b.key) + qsOf(Object.assign(Object.fromEntries(new URLSearchParams(listQS())), { f: f === 'missing' ? '' : f, p: p || '' }));
      el.innerHTML = String(html`${crumb([['Parliaments', back], [b.name]], back)}<h2>${b.name}</h2>
        <p class="ref"><b>${b.key}</b> · ${b.level} · ${b.lang || '—'}${b.opd_name && b.opd_name !== b.name ? ' · OPD: ' + b.opd_name : ''} · converter: ${b.converter || '—'} · answer dates: ${b.date_trust ? b.date_trust.replace(/_/g, ' ') : '—'}</p>
        <div class="figs"><div><span class="k">Answers</span><span class="v">${fmt(b.written)}</span></div>
          <div><span class="k">Today</span><span class="v">${share(b.attached, b.written)}</span></div>
          <div><span class="k">After repairs</span><span class="v">${share(b.attached + b.repaired, b.written)}</span></div>
          <div><span class="k">Repairs</span><span class="v">${fmt(b.repaired)}</span></div>
          <div><span class="k">Gap</span><span class="v">${fmt(b.gap)}</span></div>
          <div><span class="k">Oral</span><span class="v">${fmt(b.oral)}</span></div>
          <div><span class="k">Open</span><span class="v${b.open ? ' sig' : ''}">${fmt(b.open)}</span></div></div>
        <div class="btns">${button(1, 'Export CSV', { id: 'pexport', title: 'The interventions of the filter below, with status and repair' })}${button(2, 'Open in repair queue', b.repaired ? { href: '#/queue?b=' + encodeURIComponent(b.key) } : { disabled: true })}${button(3, 'Search its affairs', { href: '#/?b=' + encodeURIComponent(b.key) })}</div>
        ${act.length ? html`<div class="sec"><p class="sl">Repairs by action<span class="sp">${fmt(b.repaired)} rows in the repair queue</span></p>
          <div class="tblw"><table class="dense"><thead><tr><th>Action</th><th class="r">Apply now</th><th class="r">After hash</th><th class="r">Fetch</th><th class="r">Total</th></tr></thead>
          <tbody>${act.map(([a, n, h, f]) => html`<tr><td>${a}</td><td class="r">${n ? fmt(n) : '·'}</td><td class="r">${h ? fmt(h) : '·'}</td><td class="r">${f ? fmt(f) : '·'}</td><td class="r">${fmt(n + h + f)}</td></tr>`)}</tbody>
          <tfoot><tr><td>all</td><td class="r">${fmt(step.now || 0)}</td><td class="r">${fmt(step.after_hash || 0)}</td><td class="r">${fmt(step.fetch || 0)}</td><td class="r">${fmt(b.repaired)}</td></tr></tfoot></table></div></div>` : ''}
        <div class="sec"><p class="sl">Interventions<span class="sp">${fmt(list.length)} of ${fmt(nOf(null))}</span></p>
          <div class="filters"><div class="fl w2"><label class="k" for="p-f">Show</label><select id="p-f">${Object.keys(SHOW).map((f) => html`<option value="${f}" ${f === det.f ? raw('selected') : ''}>${SHOW_LABEL[f]} ${fmt(nOf(SHOW[f]))}</option>`)}</select></div></div>
          <div class="tblw"><table class="list" id="prows"><colgroup><col class="mk"><col><col class="st"></colgroup><tbody>
          ${slice.length ? slice.map((r) => affairRow(r, '#/affair/' + I.id[r] + '?b=' + encodeURIComponent(b.key), false)) : html`<tr class="none"><td></td><td colspan="2">No intervention in this filter.</td></tr>`}</tbody></table></div>
          ${pages > 1 ? html`<p class="pager"><a href="${selfQS(det.f, det.p - 1)}" class="${det.p === 0 ? 'i2' : ''}">← previous</a><span>page ${fmt(det.p + 1)} of ${fmt(pages)}</span><a href="${selfQS(det.f, det.p + 1)}">next →</a></p>` : ''}</div>
        <div class="sec"><p class="sl">Files<span class="sp">${fmt(b.lists.length)}</span></p>
          <table class="dense"><tbody>${b.lists.map((f) => html`<tr><td><a href="${docLink(f)}">${f.split('/').pop()}</a></td><td class="i2">${docLink(f).startsWith('http') ? 'repository' : 'download'}</td></tr>`)}</tbody></table></div>
        ${b.by_code && (b.by_code.B || b.by_code.b) ? html`<details class="more2"><summary>Hash decision</summary><dl class="facts"><dt>Hash</dt><dd>${HASH_LINE}</dd>
          <dt>Begin dates</dt><dd>the plan’s begin-date corrections (OPD’s load timestamp replaced by the submission date) fix another field and are not counted as repairs</dd></dl></details>` : ''}`);
      $('#p-f').addEventListener('change', (e) => { location.replace(selfQS(e.target.value, 0)); });
      $('#pexport').addEventListener('click', () => exportRows(b, list));
      wireList($('#prows tbody'));
      await fillTitles($('#prows'), slice);
    }
    async function exportRows(b, list) {
      const btn = $('#pexport');
      btn.disabled = true;
      const need = Array.from(new Set(list.map((r) => shardOf(r)[0])));
      for (let k = 0; k < need.length; k += 6) await Promise.all(need.slice(k, k + 6).map((s) => getJSON('data/s/' + s + '.json')));
      const out = [['affair_id', 'number', 'body', 'parliament', 'status', 'type', 'year', 'title', 'action', 'check', 'review', 'needs_hash_decision', 'opd_doc_id', 'target_url', 'opd_url']];
      for (const r of list) {
        const [s, o] = shardOf(r);
        const x = (await getJSON('data/s/' + s + '.json'))[o];
        const f = x[10] || x[11] || {};
        const st = ST[I.st[r]] || {};
        out.push([I.id[r], I.num[r], b.key, b.name, st.l + (st.kd ? ' · ' + st.kd : ''), C.types[I.ty[r]], I.yr[r] || '', x[1] || x[2] || x[3], f.a || '', f.t || '',
          f.r ? 'yes' : '', f.h ? 'yes' : '', f.d || '', f.u || '', opdUrl(I.id[r])]);
      }
      download('gegenprobe_' + b.key + '_' + det.f + '.csv', csv(out), 'text/csv;charset=utf-8');
      btn.disabled = false;
    }
    const focusSearch = () => { const t = $('#pl-text'); if (t) { t.focus(); t.select(); } };
    return { init, show, focusSearch };
  })();

  // ------------------------------------------------------------------------------------------ Repair queue
  const Queue = (() => {
    let Q = null;
    let st = { b: '', a: '', step: '', t: '', r: '' };
    const selected = new Set();
    let open = null;     // affair id of the repair shown on the right
    let lim = {};
    let listKey = null;
    let kOf = null;      // affair row -> queue index
    const LIM = 40;
    const listQS = () => qsOf(st);
    const hrefOf = (k) => '#/queue' + qsOf(Object.assign({}, st, { id: I.id[Q.i[k]] }));
    const load = async () => {
      if (!Q) {
        Q = await getJSON('data/queue.json');
        kOf = new Map(Q.i.map((r, k) => [r, k]));
      }
      return Q;
    };

    function init() {
      $('#qu-filters').addEventListener('change', (e) => {
        const k = { 'qu-b': 'b', 'qu-a': 'a', 'qu-step': 'step', 'qu-r': 'r', 'qu-t': 't' }[e.target.id];
        if (!k) return;
        st[k] = e.target.value;
        lim = {};
        history.replaceState(null, '', '#/queue' + qsOf(Object.assign({}, st, { id: open || '' })));
        renderList(true).then(() => { const el = $('#' + e.target.id); if (el) el.focus(); if (open == null) renderCase(); });
      });
      $('#qu tbody').addEventListener('click', (e) => {
        const m = e.target.closest('[data-more]');
        if (m) { lim[m.dataset.more] = (lim[m.dataset.more] || LIM) + 100; renderList(false); }
      });
      $('#qu tbody').addEventListener('change', (e) => {
        const cb = e.target.closest('input[type="checkbox"]');
        if (!cb) return;
        toggle(Number(cb.dataset.k), cb.checked);
      });
      wireList($('#qu tbody'));
      $('#qu-count').addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        if (b.dataset.do === 'all') matching().forEach((k) => selected.add(k));
        if (b.dataset.do === 'none') selected.clear();
        $$('#qu input[type="checkbox"]').forEach((cb) => { cb.checked = selected.has(Number(cb.dataset.k)); });
        counts();
        renderCase();
      });
    }
    function toggle(k, on) {
      if (on) selected.add(k); else selected.delete(k);
      const cb = $('#qu input[data-k="' + k + '"]');
      if (cb) cb.checked = on;
      counts();
      renderCase();  // the action buttons carry the selection's counts
    }
    function match(k) {
      const r = Q.i[k];
      return (!st.b || C.bodies[rowBody[r]].key === st.b) && (!st.a || C.actions[Q.a[k]] === st.a) && (!st.step || Q.step[k] === st.step)
        && (!st.t || Q.t[k] === st.t) && (!st.r || (st.r === 'review' ? Q.r[k] === 1 : Q.r[k] === 0));
    }
    function matching() { const out = []; for (let k = 0; k < Q.i.length; k++) if (match(k)) out.push(k); return out; }
    const filtered = () => Object.values(st).some(Boolean);

    async function show(params) {
      const want = { b: params.get('b') || '', a: params.get('a') || '', step: params.get('step') || (params.get('h') === 'yes' ? 'after_hash' : ''),
        t: params.get('t') || '', r: params.get('r') || '' };
      const id = params.get('id') ? Number(params.get('id')) : null;
      const box = $('#v-queue');
      setOpen(box, id != null);
      if (!Q) { $('#qu tbody').innerHTML = '<tr class="none"><td colspan="3">Loading the queue…</td></tr>'; await load(); }
      const changed = Object.keys(want).some((k) => want[k] !== st[k]) || listKey == null;
      st = want;
      open = id;
      if (changed) { lim = {}; await renderList(true); } else {
        $$('#qu tr.it').forEach((tr) => tr.setAttribute('aria-selected', String(Number(tr.dataset.id) === open)));
        const on = $('#qu tr.it[aria-selected="true"]');
        if (open != null && !on) await renderList(false); else if (on) on.scrollIntoView({ block: 'nearest' });
      }
      renderCase();
    }

    function filters() {
      const bodies = C.bodies.filter((b) => b.repaired > 0).sort((a, b) => a.name.localeCompare(b.name));
      const tiers = Array.from(new Set(Q.t)).sort();
      $('#qu-filters').innerHTML = String(html`
        ${select('qu-b', 'Parliament', [['', 'All']].concat(bodies.map((b) => [b.key, b.name + ' (' + fmt(b.repaired) + ')'])), st.b, 'w2')}
        ${select('qu-a', 'Action', [['', 'All']].concat(C.actions.map((a) => [a, a])), st.a)}
        ${select('qu-step', 'Step', [['', 'All']].concat(Object.keys(STEP_SHORT).map((s) => [s, STEP_SHORT[s]])), st.step)}
        ${select('qu-r', 'Status', [['', 'All'], ['ready', 'ready'], ['review', 'review']], st.r)}
        ${select('qu-t', 'Check', [['', 'All']].concat(tiers.map((t) => [t, tierShort(t)])), st.t, 'w2')}`);
    }
    function counts() {
      const n = matching().length;
      $('#qu-count').innerHTML = String(html`<span><b>${fmt(n)}</b> rows · <b>${fmt(selected.size)}</b> selected</span>
        <button class="tb" type="button" data-do="all">select all ${fmt(n)}</button><button class="tb" type="button" data-do="none" ${selected.size ? '' : raw('disabled')}>clear</button>
        <span class="keys">j/k · Space select · Enter</span>`);
    }
    function row(k) {
      const r = Q.i[k];
      const b = C.bodies[rowBody[r]];
      const t = titleNow(r);
      const href = hrefOf(k);
      const target = Q.d[k] ? 'doc ' + Q.d[k] : Q.u[k] ? hostOf(Q.u[k]) : '';
      return html`<tr class="it" data-href="${href}" data-id="${I.id[r]}" data-k="${k}" aria-selected="${I.id[r] === open}">
        <td class="ck"><input type="checkbox" data-k="${k}" aria-label="Select ${I.num[r]}" ${selected.has(k) ? raw('checked') : ''}></td>
        <td class="ti"><b><a class="${t == null ? 'pending' : ''}" data-row="${r}" href="${href}" tabindex="-1">${t == null ? '…' : (t || '(no title in OPD)')}</a></b><span class="code">${I.num[r]} · ${b.name}</span></td>
        <td class="aw">${C.actions[Q.a[k]]}${Q.r[k] ? html` · <span class="sig">review</span>` : ''}<span class="kd" title="${C.tiers[Q.t[k]] || ''}">${target || tierShort(Q.t[k])}</span></td></tr>`;
    }
    async function renderList(top) {
      filters();
      const list = matching();
      const bd = C.bound;
      const parts = [];
      const shown = [];
      let pin = open != null ? kOf.get(byId.get(open)) : undefined;
      for (const s of Object.keys(STEPS)) {
        const rows = list.filter((k) => Q.step[k] === s);
        if (!rows.length) continue;
        const l = lim[s] || LIM;
        const page = rows.slice(0, l);
        if (pin !== undefined && page.includes(pin)) pin = undefined;
        // unfiltered, a step's count is the stated number (bound: claims_app.json); filtered, the share of it
        parts.push(filtered() ? html`<tr class="grp"><td colspan="3">${STEPS[s]} · ${fmt(rows.length)} of ${fmt(bd[s])}</td></tr>`
          : html`<tr class="grp"><td colspan="3" data-claims="queue">${STEPS[s]} · ${fmt(bd[s])}</td></tr>`);
        page.forEach((k) => { parts.push(row(k)); shown.push(Q.i[k]); });
        if (rows.length > l) parts.push(moreRow(s, rows.length - l));
      }
      if (pin !== undefined) { parts.unshift(html`<tr class="grp"><td colspan="3">Open · 1</td></tr>`, row(pin)); shown.push(Q.i[pin]); }
      if (!parts.length) parts.push(html`<tr class="none"><td colspan="3">No repair with these filters.</td></tr>`);
      $('#qu tbody').innerHTML = String(html`${parts}`);
      counts();
      listKey = listQS();
      if (top) $('#qu-wrap').scrollTop = 0;
      const on = $('#qu tr.it[aria-selected="true"]');
      if (on) on.scrollIntoView({ block: 'nearest' });
      fillTitles($('#qu tbody'), shown);
    }
    let caseSeq = 0;
    async function renderCase() {
      const el = $('#qu-case');
      const my = ++caseSeq;
      let k = open != null ? kOf.get(byId.get(open)) : undefined;
      if (k === undefined) { const first = $('#qu tr.it'); k = first ? Number(first.dataset.k) : undefined; if (first && open == null) first.setAttribute('aria-selected', 'true'); }
      const back = '#/queue' + listQS();
      if (k === undefined) { el.innerHTML = String(html`${crumb([['Repair queue', back]], back)}<p class="empty">No repair selected.</p>`); return; }
      const r = Q.i[k];
      const b = C.bodies[rowBody[r]];
      const d = await detailRow(r);
      if (my !== caseSeq) return;
      const code = I.st[r];
      const title = d.tde || d.tfr || d.tit || '(no title in OPD)';
      const selRelink = Array.from(selected).filter((x) => Q.s[x] === 'be' && C.actions[Q.a[x]] === 'relink');
      const selBern = selRelink.filter((x) => Q.p[x] === 1);
      const ev = evidenceFacts(d);
      const rp = repairFacts(code, d, I.id[r], b).filter((x) => x[0] !== 'Queue');
      const f = d.fix || {};
      el.innerHTML = String(html`${crumb([['Repair queue', back], [STEPS[Q.step[k]], '#/queue' + qsOf(Object.assign({}, st, { step: Q.step[k] }))], [I.num[r]]], back)}
        <h2>${title}</h2>
        <p class="ref"><b>${I.num[r]}</b> · OPD ${I.id[r]} · ${b.name} · ${b.key} · ${I.yr[r] || 'year unknown'}</p>
        <p class="state${Q.r[k] ? ' sig' : ''}">${Q.r[k] ? '[ ]' : '[→]'} ${C.actions[Q.a[k]]} · ${STEP_SHORT[Q.step[k]]} · ${tierShort(Q.t[k])}${Q.r[k] ? ' · review first' : ' · ready'}${Q.p[k] ? ' · in the Bern plan' : ''}</p>
        <div class="sec"><p class="sl">Where the answer is</p>${whereHTML(code, d, I.id[r])}
          <div class="btns">${button(1, 'Export selection CSV · ' + fmt(selected.size), selected.size ? { id: 'qcsv' } : { id: 'qcsv', disabled: true, title: 'Select rows with the checkboxes (Space)' })}
          ${button(2, 'Export Bern SQL · ' + fmt(selBern.length), selBern.length ? { id: 'qsql', title: 'The guarded UPDATE statements of the selected Bern relinks, copied from the dry-run plan' + (selRelink.length > selBern.length ? '; ' + fmt(selRelink.length - selBern.length) + ' review rows are not in the plan' : '') } : { id: 'qsql', disabled: true, title: 'Select Bern relinks (step: after hash) to export their statements from the dry-run plan' })}
          ${button(3, 'Open affair', { href: '#/affair/' + I.id[r] + '?b=' + encodeURIComponent(b.key) })}
          ${button(4, selected.has(k) ? 'Remove from selection' : 'Add to selection', { id: 'qsel' })}</div></div>
        <div class="sec"><div class="ftg">${[['Evidence', ev], ['Repair', rp]].filter((x) => x[1].length).map(([h, rows]) => html`<div class="ftc"><p class="lh">${h}</p>${facts(rows)}</div>`)}</div>
          ${f.q ? html`<p class="quote">“${f.q}”</p>` : ''}</div>
        <details class="more2"><summary>Details</summary><dl class="facts"><dt>Check</dt><dd>${tierText(Q.t[k])}</dd>
          ${Q.h[k] ? html`<dt>Hash decision</dt><dd>${HASH_LINE}</dd>` : ''}
          <dt>Selection</dt><dd>checkboxes or Space; the CSV lists the selected rows, the SQL copies the plan’s statements of the selected Bern relinks</dd></dl></details>`);
      $('#qcsv').addEventListener('click', exportSelection);
      $('#qsql').addEventListener('click', () => exportSQL(selBern));
      $('#qsel').addEventListener('click', () => toggle(k, !selected.has(k)));
    }
    const exportRows = (ks, name) => {
      const rows = [['affair_id', 'number', 'body', 'parliament', 'action', 'step', 'source', 'check', 'status', 'needs_hash_decision', 'in_bern_plan', 'opd_doc_id', 'target_url', 'opd_url']];
      ks.slice().sort((a, b) => a - b).forEach((k) => {
        const r = Q.i[k];
        const b = C.bodies[rowBody[r]];
        rows.push([I.id[r], I.num[r], b.key, b.name, C.actions[Q.a[k]], Q.step[k], Q.s[k], Q.t[k], Q.r[k] ? 'review' : 'ready', Q.h[k] ? 'yes' : 'no',
          Q.p[k] ? 'yes' : 'no', Q.d[k], Q.u[k], opdUrl(I.id[r])]);
      });
      download(name, csv(rows), 'text/csv;charset=utf-8');
    };
    function exportSelection() {
      if (!selected.size) { toast('No repair selected: open the repair queue and tick rows'); return; }
      exportRows(Array.from(selected), 'gegenprobe_repairs_' + selected.size + '.csv');
    }
    async function exportAll() {
      await load();
      exportRows(Q.i.map((_, k) => k), 'gegenprobe_repairs_all.csv');
    }
    async function exportSQL(ks) {
      let plan;
      try { plan = await getText(C.bern_plan); } catch (e) { toast('Could not read the plan'); return; }
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
    }
    const toggleCurrent = () => {
      const tr = $('#qu tr.it[aria-selected="true"]');
      if (tr) toggle(Number(tr.dataset.k), !selected.has(Number(tr.dataset.k)));
    };
    return { init, show, exportSelection, exportAll, toggleCurrent, selectedCount: () => selected.size };
  })();

  // ------------------------------------------------------------------------------------------ About
  const About = (() => {
    let done = false;
    function show(params) {
      if (!done) render();
      done = true;
      if (params.get('s')) { const el = $('#a-' + params.get('s')); if (el) el.scrollIntoView(); } else window.scrollTo(0, 0);
    }
    function render() {
      const bd = C.bound;
      const vlabel = { roles: 'needs roles', body: 'body-specific', untested: 'untested' };
      const groups = {};
      C.downloads.forEach((d) => { (groups[d.g] = groups[d.g] || []).push(d); });
      const kb = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' kB');
      $('#v-about').innerHTML = String(html`${crumb([['About']])}<h2>Gegenprobe</h2>
        <p class="ref">OpenParlData answer check · Team 444 · Hack Apertus 2026, Track 2A · OPD snapshot ${ddmmyyyy(C.snapshot)} · build ${C.build}</p>
        <div class="sec" data-claims="about"><dl class="facts wide">
          <dt>Scope</dt><dd><b>${fmt(bd.written)}</b> interventions with a recorded government answer · OpenParlData (OPD)</dd>
          <dt>Check</dt><dd>answer text attached? if not: where it is, which repair</dd>
          <dt>Answer text</dt><dd><b>${bd.share_today}</b> today → <b>${bd.share_after}</b> after the <b>${fmt(bd.repaired)}</b> repairs</dd>
          <dt>Repairs</dt><dd>${fmt(bd.now)} apply now · ${fmt(bd.after_hash)} after OPD’s hash decision · ${fmt(bd.fetch)} fetch · keyed on OPD ids, no model</dd>
          <dt>Schema verdict</dt><dd>${bd.fields} fields: ${bd.need_roles} need roles · body-specific: ${bd.body_specific} field and 2 constructs · ${bd.untested} untested · one schema works if each field names its value’s role</dd>
          <dt>Records</dt><dd>${fmt(bd.records)} v0.2 records validate · ${bd.record_parliaments} parliaments</dd>
          <dt>Provenance</dt><dd>document · page · character span · route (rule, metadata, model) · a missing value is a typed gap</dd>
          <dt>Apertus</dt><dd>opt-in; a reviewer confirms each value it proposes · the repairs use no model</dd>
        </dl></div>
        <div class="sec" data-claims="about"><p class="sl">Apertus, registered tests</p>
          <div class="tblw"><table class="dense"><thead><tr><th>Test</th><th class="r">Result</th><th>Measure</th></tr></thead><tbody>
            <tr><td>P2</td><td class="r">${bd.p2_pointer[0]}/${bd.p2_pointer[1]}</td><td>answer dates found in ${bd.p2_parliaments} parliaments without rules · rules alone ${bd.p2_rules[0]}/${bd.p2_rules[1]}</td></tr>
            <tr><td>P10</td><td class="r">+${bd.p10_points}</td><td>points author-role recall in ${bd.p10_parliaments} parliaments without rules · pair precision ${bd.p10_precision}, rules alone ${bd.p10_rules_precision}</td></tr>
            <tr><td>P7</td><td class="r">${bd.p7[0]}/${bd.p7[1]}</td><td>sampled review-queue rows Apertus moved up are the government’s answer</td></tr>
          </tbody></table></div></div>
        <div class="sec"><p class="sl"><span data-claims="about">Schema fields · ${bd.fields}</span><span class="sp">verdict per field; evidence on hover</span></p>
          <div class="tblw"><table class="dense flds"><thead><tr><th>Field</th><th>Verdict</th><th>Fragile</th><th>Tested by</th><th>Evidence</th></tr></thead>
          <tbody>${C.fields.map((f) => html`<tr title="${f.why}"><td>${f.name}</td><td>${vlabel[f.verdict]}</td><td>${f.fragile ? html`<span class="sig">fragile</span>` : '·'}</td><td>${f.test || '·'}</td><td class="why">${f.why}</td></tr>`)}</tbody></table></div></div>
        <div class="sec" id="a-downloads"><p class="sl">Downloads<span class="sp">${fmt(C.downloads.length)} files, byte-identical copies of the repository’s lists</span></p>
          <div class="tblw" data-meta="files"><table class="dense dl"><tbody>${Object.entries(groups).map(([g, fs]) => html`<tr class="g"><td colspan="3">${g} · ${fmt(fs.length)}</td></tr>
            ${fs.map((d) => html`<tr><td class="f"><a href="${d.h}">${d.f}</a></td><td class="w">${d.w}</td><td class="m">${d.r != null ? fmt(d.r) + ' rows · ' : ''}${kb(d.b)}</td></tr>`)}`)}</tbody></table></div></div>
        <div class="sec"><p class="sl">Links</p><div class="btns">${button(1, 'Repository', { href: C.repo })}${button(2, 'Technical report (PDF)', { href: C.links.report })}${button(3, 'Decision page', { href: C.links.decision_en })}${button(4, 'Entscheidungsseite (DE)', { href: C.links.decision_de })}</div></div>`);
    }
    return { show };
  })();

  // ------------------------------------------------------------------------------------------ keys
  const Keys = (() => {
    const list = () => ({ lookup: '#lk', parliaments: '#pl', queue: '#qu' }[view]);
    function move(step) {
      const sel = list();
      if (!sel) return;
      const rows = $$(sel + ' tr.it');
      if (!rows.length) return;
      const at = rows.findIndex((tr) => tr.getAttribute('aria-selected') === 'true');
      const next = rows[Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : at + step))];
      if (next) { location.replace(next.dataset.href); next.scrollIntoView({ block: 'nearest' }); }
    }
    function back() {
      const { parts, params } = parse();
      if (view === 'lookup' && parts[0] === 'affair') location.hash = '#/' + qsOf(Object.fromEntries(params));
      else if (view === 'parliaments' && parts[0] === 'parliament') { params.delete('f'); params.delete('p'); location.hash = '#/parliaments' + qsOf(Object.fromEntries(params)); }
      else if (view === 'queue' && params.get('id')) { params.delete('id'); location.hash = '#/queue' + qsOf(Object.fromEntries(params)); }
    }
    function init() {
      document.addEventListener('keydown', (e) => {
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        const a = document.activeElement;
        const typing = a && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName) && a.type !== 'checkbox';
        if (e.key === 'Escape') {
          if ($('#xmenu').open) { $('#xmenu').open = false; return; }
          if (typing) { a.blur(); return; }
          back();
          return;
        }
        if (typing) return;
        if (e.key === '/') {
          e.preventDefault();
          if (view === 'parliaments') Parliaments.focusSearch();
          else { if (view !== 'lookup') location.hash = '#/'; setTimeout(Lookup.focusSearch, 0); }
        } else if (e.key === 'j' || e.key === 'k') {
          e.preventDefault();
          move(e.key === 'j' ? 1 : -1);
        } else if (e.key === 'Enter' && (!a || a === document.body || a.closest('.register'))) {
          const tr = $((list() || '#none') + ' tr.it[aria-selected="true"]');
          if (tr) { e.preventDefault(); location.hash = tr.dataset.href; setTimeout(() => { const c = $('#v-' + view + ' .case'); if (c) c.focus(); }, 0); }
        } else if (/^[1-4]$/.test(e.key)) {
          const scope = view === 'about' ? $('#v-about') : $('#v-' + view + ' .case');
          const b = scope && $('[data-key="' + e.key + '"]', scope);
          if (b && !b.disabled) { e.preventDefault(); b.click(); }
        } else if (e.key === ' ' && view === 'queue' && (!a || a === document.body || a.closest('.register'))) {
          e.preventDefault();
          Queue.toggleCurrent();
        }
      });
    }
    return { init, move };
  })();

  window.addEventListener('DOMContentLoaded', async () => {
    Shell.theme();
    try {
      await boot();
    } catch (e) {
      $('#loading').textContent = 'Could not load the data (' + e.message + '). Serve this folder over HTTP, e.g. python -m http.server.';
      return;
    }
    $('#loading').hidden = true;
    Shell.status();
    Shell.menu();
    Lookup.init();
    Parliaments.init();
    Queue.init();
    Keys.init();
    window.addEventListener('hashchange', route);
    route();
  });
})();
