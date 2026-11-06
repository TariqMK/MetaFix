// MetaFix product page: live app preview, feature demos and latest-release download links.
(() => {
  'use strict';

  const REPO = 'TariqMK/MetaFix';
  const ASSET = { windows: /windows-x64\.zip$/i, macos: /macos-arm64\.zip$/i, linux: /linux-x64\.tar\.gz$/i };
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = id => document.getElementById(id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

  // ── Dates ──────────────────────────────────────────────────────────────────
  // Dates are "YYYY-MM-DD hh:mm:ss" strings, handled in UTC so no DST shifts apply.
  const parse = s => { const [y, m, d, h, mi, se] = s.split(/[- :]/).map(Number); return { y, m, d, h, mi, se }; };
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  const fmt = t => `${pad(t.getUTCFullYear(), 4)}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())} ${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}:${pad(t.getUTCSeconds())}`;

  // Years and months first, clamped to the month's last day, then days, hours and minutes.
  function shiftDate(s, sh) {
    const p = parse(s);
    const months = p.y * 12 + (p.m - 1) + sh.years * 12 + sh.months;
    const y = Math.floor(months / 12), m = months - y * 12;
    const last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const base = Date.UTC(y, m, Math.min(p.d, last), p.h, p.mi, p.se);
    return fmt(new Date(base + ((sh.days * 24 + sh.hours) * 60 + sh.minutes) * 60000));
  }

  // Wraps each date part; parts that differ from `was` are underlined in gold.
  function dateHTML(s, was) {
    const parts = s.match(/\d+|\D/g), old = was ? was.match(/\d+|\D/g) : null;
    let out = '', i = 0;
    for (const part of parts) {
      const changed = old && /\d/.test(part) && old[i] !== part;
      out += changed ? `<span class="ch">${part}</span>` : (/\d/.test(part) ? part : `<span class="p">${esc(part)}</span>`);
      i++;
    }
    const cut = out.indexOf('<span class="p"> </span>');
    return `<span class="d">${out.slice(0, cut)}<span class="tm">${out.slice(cut)}</span></span>`;
  }

  function describeShift(sh) {
    const parts = [['years', 'year'], ['months', 'month'], ['days', 'day'], ['hours', 'hour'], ['minutes', 'minute']]
      .filter(([k]) => sh[k])
      .map(([k, u]) => `${plural(Math.abs(sh[k]), u)} ${sh[k] > 0 ? 'later' : 'earlier'}`);
    if (!parts.length) return 'Enter an amount to move each date';
    const last = parts.pop();
    return `Moves each date ${parts.length ? `${parts.join(', ')} and ${last}` : last}`;
  }

  // ── Background motif: the dial ticks around the logo's arrow ──────────────
  const dial = document.querySelector('.motif #dial');
  if (dial) {
    let ticks = '';
    for (let i = 0; i < 60; i++) {
      const a = (i / 60) * Math.PI * 2, major = i % 5 === 0;
      const r1 = 372, r2 = major ? 400 : 386;
      ticks += `<line x1="${500 + r1 * Math.sin(a)}" y1="${500 - r1 * Math.cos(a)}" x2="${500 + r2 * Math.sin(a)}" y2="${500 - r2 * Math.cos(a)}"/>`;
    }
    dial.innerHTML = ticks;
  }

  // ── Hero: live preview of the app window ──────────────────────────────────
  const FILES = [
    { n: 'DSC_0841.JPG', d: '2023-06-15 07:40:11', s: 'DateTimeOriginal' },
    { n: 'DSC_0842.JPG', d: '2023-06-15 07:41:56', s: 'DateTimeOriginal' },
    { n: 'IMG-20240615-WA0004.jpg', d: '2025-01-03 21:14:09', s: 'FileCreateDate', fs: true },
    { n: 'IMG-20240615-WA0007.jpg', d: '2025-01-03 21:14:09', s: 'FileCreateDate', fs: true },
    { n: 'IMG_4012.JPG', d: '2024-06-14 09:12:40', s: 'DateTimeOriginal' },
    { n: 'IMG_4013.JPG', d: '2024-06-14 09:15:02', s: 'DateTimeOriginal' },
    { n: 'IMG_4025.MOV', d: '2024-06-16 11:05:44', s: 'CreateDate' },
    { n: 'PXL_20240614_181502.jpg', d: '2024-06-14 18:15:02', s: 'DateTimeOriginal' },
    { n: 'Scan_beach_01.png', d: '2025-01-03 21:14:09', s: 'FileCreateDate', fs: true },
    { n: 'VID_20240616_093011.mp4', d: '2024-06-16 09:30:11', s: 'CreateDate' },
  ];
  const SET_DATE = '2019-06-14 18:30:00';
  const FS = [2, 3, 8];

  // Each step is one second. A step returns the full view state for that moment.
  function fresh() { return FILES.map(f => ({ ...f, nd: null, done: false })); }
  let files = fresh();
  const view = { mode: 'shift', filter: null, sel: [], shift: { years: 0, months: 0, days: 0, hours: 0, minutes: 0 },
                 typing: null, preview: false, undo: false, status: '10 files loaded', done: false, rename: false };

  const scope = () => view.sel.length ? plural(view.sel.length, 'selected file') : `all ${plural(files.length, 'file')}`;
  const STEPS = [
    () => { files = fresh(); Object.assign(view, { mode: 'shift', filter: null, sel: [], preview: false, done: false, undo: false, rename: false, typing: null, status: '10 files loaded', shift: { years: 0, months: 0, days: 0, hours: 0, minutes: 0 } }); },
    () => { view.sel = [0, 1]; view.status = '2 files selected'; },
    () => { view.shift.years = 1; view.typing = 'years'; },
    () => { view.shift.hours = 2; view.typing = 'hours'; },
    () => { view.typing = null; view.preview = true; view.sel.forEach(i => { files[i].nd = shiftDate(files[i].d, view.shift); }); view.status = '2 files ready to write. Nothing has been written yet.'; },
    null, null,
    () => { view.sel.forEach(i => { files[i].d = files[i].nd; files[i].nd = null; files[i].done = true; }); Object.assign(view, { preview: false, done: true, undo: true, status: '2 files updated. Originals are in the BACKUPS folder beside each file.' }); },
    null, null,
    () => { files.forEach(f => { f.done = false; }); Object.assign(view, { mode: 'manual', sel: [], done: false, filter: 'FileCreateDate', status: '3 shown of 10 files' }); },
    () => { view.rename = true; },
    () => { view.sel = FS.slice(); view.status = '3 files selected'; },
    () => { view.preview = true; FS.forEach(i => { files[i].nd = SET_DATE; }); view.status = '3 files ready to write. Nothing has been written yet.'; },
    null, null,
    () => { FS.forEach(i => { files[i].d = SET_DATE; files[i].n = '2019-06-14_18-30-00_' + files[i].n; files[i].nd = null; files[i].done = true; }); Object.assign(view, { preview: false, done: true, status: '3 files updated. Originals are in the BACKUPS folder beside each file.' }); },
    null, null, null,
  ];

  function renderPreview() {
    const rows = view.filter ? files.map((f, i) => [f, i]).filter(([f]) => f.s === view.filter) : files.map((f, i) => [f, i]);
    $('pvRows').innerHTML = rows.map(([f, i]) => {
      const sel = view.sel.includes(i);
      const src = `<b>${f.s}</b>${f.fs ? '<span> · file system</span>' : ''}`;
      return `<tr class="${sel ? 'sel' : ''}"><td class="c-box"><span class="cb${sel ? ' on' : ''}"></span></td>` +
        `<td>${esc(f.n)}</td><td>${dateHTML(f.d)}</td><td class="src">${src}</td>` +
        `<td>${f.nd ? dateHTML(f.nd, f.d) : '<span class="dash">–</span>'}</td>` +
        `<td>${f.done ? '<span class="st-ok"><svg class="i" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>Done</span>' : ''}</td></tr>`;
    }).join('');
    const shown = rows.length;
    const all = $('pvAll');
    all.className = 'cb' + (view.sel.length && view.sel.length === shown ? ' on' : view.sel.length ? ' part' : '');
    $('pvCount').textContent = view.filter ? `${shown} shown · ${files.length} total` : `${files.length} files${view.sel.length ? ` · ${view.sel.length} selected` : ''}`;
    const filter = $('pvFilter');
    filter.textContent = view.filter || 'All sources';
    filter.classList.toggle('on', !!view.filter);
    $('pvStatus').textContent = view.status;
    $('pvSummary').classList.toggle('done', view.done);
    $('pvCommit').textContent = `${view.preview ? 'Apply to' : 'Preview'} ${scope()}`;
    $('pvUndo').classList.toggle('off', !view.undo);
    $('pvRename').classList.toggle('on', view.rename);
    document.querySelectorAll('.w-tabs span').forEach(t => t.classList.toggle('on', t.dataset.m === view.mode));

    const panel = $('pvPanel');
    if (view.mode === 'shift') {
      const f = (k, label) => `<div><span class="w-fl">${label}</span><div class="w-in${view.typing === k ? ' typing' : ''}">${view.shift[k]}</div></div>`;
      panel.innerHTML = `<span class="w-fl">Move by</span><div class="w-sg">${f('years', 'Years')}${f('months', 'Months')}${f('days', 'Days')}${f('hours', 'Hours')}${f('minutes', 'Minutes')}</div>` +
        `<p class="w-say">${describeShift(view.shift)}</p>`;
    } else {
      panel.innerHTML = `<span class="w-fl">New date and time</span><div class="w-in">${SET_DATE.replace(' ', '  ')}</div>` +
        `<p class="w-say" style="font-weight:400;color:var(--text2)">${view.rename ? 'Adds a prefix, like 2019-06-14_18-30-00_photo.jpg' : ''}</p>`;
    }
  }

  let step = 0, timer = null;
  function tick() {
    if (STEPS[step]) STEPS[step]();
    renderPreview();
    step = (step + 1) % STEPS.length;
  }
  if (reduced) {
    // One static frame: the shift preview, ready to apply.
    for (let i = 0; i <= 4; i++) if (STEPS[i]) STEPS[i]();
    view.typing = null;
    renderPreview();
  } else {
    tick();
    const run = () => { if (!timer) timer = setInterval(tick, 1000); };
    const stop = () => { clearInterval(timer); timer = null; };
    document.addEventListener('visibilitychange', () => (document.hidden ? stop() : run()));
    if (!document.hidden) run();
  }

  // ── Feature: shift demo ───────────────────────────────────────────────────
  const SAMPLES = [
    ['DSC_0841.JPG', '2023-06-15 07:40:11'],
    ['DSC_0857.JPG', '2023-06-15 14:02:37'],
    ['DSC_0903.JPG', '2023-06-30 23:58:02'],
    ['DSC_0911.MOV', '2023-07-01 01:15:48'],
  ];
  const LIMITS = { years: 99, months: 99, days: 999, hours: 999, minutes: 9999 };
  const sh = { years: 1, months: 0, days: 0, hours: -2, minutes: 0 };
  const inputs = $('shiftInputs');
  inputs.innerHTML = [['years', 'Years'], ['months', 'Months'], ['days', 'Days'], ['hours', 'Hours'], ['minutes', 'Minutes']]
    .map(([k, label]) => `<div><label for="sh-${k}">${label}</label><div class="stepper">` +
      `<button type="button" data-k="${k}" data-d="-1" aria-label="${label} minus one">−</button>` +
      `<input id="sh-${k}" type="number" inputmode="numeric" value="${sh[k]}" data-k="${k}">` +
      `<button type="button" data-k="${k}" data-d="1" aria-label="${label} plus one">+</button></div></div>`).join('');

  function renderShift() {
    $('shiftSay').textContent = describeShift(sh);
    $('diffList').innerHTML = SAMPLES.map(([n, d]) => {
      const nd = shiftDate(d, sh);
      return `<div class="diff-row"><span class="name">${n}</span><span class="old">${dateHTML(d)}</span><span class="arrow">→</span><span>${dateHTML(nd, d)}</span></div>`;
    }).join('');
  }
  const setShift = (k, v) => {
    const n = Math.max(-LIMITS[k], Math.min(LIMITS[k], parseInt(v, 10) || 0));
    sh[k] = n;
    $('sh-' + k).value = n;
    renderShift();
  };
  inputs.addEventListener('click', e => { const b = e.target.closest('button'); if (b) setShift(b.dataset.k, sh[b.dataset.k] + Number(b.dataset.d)); });
  inputs.addEventListener('input', e => { if (e.target.dataset.k) { const k = e.target.dataset.k; sh[k] = Math.max(-LIMITS[k], Math.min(LIMITS[k], parseInt(e.target.value, 10) || 0)); renderShift(); } });
  inputs.addEventListener('change', e => { if (e.target.dataset.k) setShift(e.target.dataset.k, e.target.value); });
  renderShift();

  // ── Feature: read from / filter demo ──────────────────────────────────────
  const SOURCES = [null, 'DateTimeOriginal', 'CreateDate', 'FileCreateDate'];
  let srcFilter = null;
  function renderSources() {
    $('srcChips').innerHTML = SOURCES.map(s => {
      const n = s ? FILES.filter(f => f.s === s).length : FILES.length;
      return `<button type="button" class="chip" data-s="${s || ''}" aria-pressed="${s === srcFilter}">${s || 'All sources'}<span class="n">${n}</span></button>`;
    }).join('');
    $('srcList').innerHTML = FILES.filter(f => !srcFilter || f.s === srcFilter).slice(0, 6).map(f =>
      `<div class="src-row"><span class="name">${esc(f.n)}</span><span class="src"><b>${f.s}</b>${f.fs ? ' · file system' : ''}</span></div>`).join('');
  }
  $('srcChips').addEventListener('click', e => { const b = e.target.closest('.chip'); if (b) { srcFilter = b.dataset.s || null; renderSources(); } });
  renderSources();

  // ── Feature: undo demo ────────────────────────────────────────────────────
  const TREE_FILES = [['DSC_0841.JPG', '2023-06-15 07:40:11'], ['DSC_0842.JPG', '2023-06-15 07:41:56']];
  let applied = false, backups = false;
  function renderTree(animate) {
    const shiftBy = { years: 1, months: 0, days: 0, hours: 2, minutes: 0 };
    let html = '<div class="dir">Holiday 2023/</div>';
    for (const [n, d] of TREE_FILES) {
      const shown = applied ? dateHTML(shiftDate(d, shiftBy), d) : dateHTML(d);
      html += `<div class="in1"><span>${n}</span><span class="note">${shown}</span></div>`;
    }
    if (backups) {
      const cls = animate && applied ? ' new' : '';
      html += `<div class="in1 dir${cls}"><span>BACKUPS/</span></div>`;
      for (const [n] of TREE_FILES) html += `<div class="in2${cls}"><span>${n}</span><span class="note">original</span></div>`;
    }
    $('tree').innerHTML = html;
    $('undoToggle').textContent = applied ? 'Undo' : 'Apply shift of 1 year and 2 hours';
  }
  $('undoToggle').addEventListener('click', () => {
    applied = !applied;
    if (applied) backups = true; // Undo keeps the backup until Clean backups deletes it.
    renderTree(true);
  });
  renderTree(false);

  // ── Download wiring ───────────────────────────────────────────────────────
  // Every link already points at the Releases page; this only makes them direct.
  const ua = navigator.userAgent;
  const mobile = /Android|iPhone|iPad|iPod/i.test(ua) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(ua));
  const os = mobile ? null : /Windows/i.test(ua) ? 'windows' : /Mac/i.test(ua) ? 'macos' : /Linux|X11/i.test(ua) ? 'linux' : null;
  const NAMES = { windows: 'Windows', macos: 'macOS', linux: 'Linux' };
  const hero = $('heroDownload');
  if (os) {
    hero.textContent = `Download for ${NAMES[os]}`;
    document.querySelector(`.card[data-os="${os}"]`)?.classList.add('mine');
  } else {
    hero.href = '#download';
  }

  fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: 'application/vnd.github+json' } })
    .then(r => (r.ok ? r.json() : Promise.reject(r.status)))
    .then(rel => {
      if (!rel || !rel.tag_name) return;
      for (const asset of rel.assets || []) {
        for (const [key, re] of Object.entries(ASSET)) {
          if (!re.test(asset.name)) continue;
          const card = document.querySelector(`.card[data-os="${key}"]`);
          if (card) {
            card.href = asset.browser_download_url;
            const size = card.querySelector('[data-size]');
            size.textContent = `${size.textContent} · ${Math.round(asset.size / 1048576)} MB`;
          }
          if (key === os) hero.href = asset.browser_download_url;
        }
      }
      const date = rel.published_at ? new Date(rel.published_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : '';
      $('dlMeta').textContent = `${rel.tag_name}${date ? ` · released ${date}` : ''}`;
      $('heroMeta').textContent = `${rel.tag_name} · Free and open source · Windows, macOS, Linux`;
      $('pvVer').textContent = rel.tag_name;
    })
    .catch(() => {});
})();
