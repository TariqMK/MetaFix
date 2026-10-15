
// ── STATE ──────────────────────────────────────────────────────────────────────
let files = [];         // [{path, name}]
let currentMeta = {};   // path -> {value: "2026:06:06 21:34:15", field: "CreateDate"}
let previewMeta = {};   // path -> date string
let statusMap = {};     // path -> 'ready'|'ok'|'err'|'loading'
let selectedPaths = new Set();
let currentMode = 'manual';
let destFieldKeys = [];
let hasLastBatch = false;
let activeFieldFilter = '';  // field name to filter table by, or '' for all

// ── INIT ───────────────────────────────────────────────────────────────────────
async function init() {
  const cfg = await api('/api/config');
  if (cfg.exiftool_path) {
    document.getElementById('exifStatus').textContent = cfg.exiftool_path;
    document.getElementById('exifStatus').classList.add('ok');
  }
  if (cfg.ffmpeg_path) {
    document.getElementById('ffmpegStatus').innerHTML = cfg.ffmpeg_path +
      ' <span style="color:var(--text3);font-size:10px;">(AVI)</span>';
    document.getElementById('ffmpegStatus').classList.add('ok');
  }

  // populate copy source
  const cs = document.getElementById('copySource');
  cfg.copy_source_fields.forEach(f => {
    const o = document.createElement('option'); o.value = f; o.textContent = f; cs.appendChild(o);
  });

  // populate dest fields
  destFieldKeys = cfg.dest_fields;
  const grid = document.getElementById('destFields');
  destFieldKeys.forEach(f => {
    const label = document.createElement('label');
    label.className = 'checkbox-row';
    label.innerHTML = `<input type="checkbox" class="dest-cb" data-field="${f}" checked/><span>${f}</span>`;
    grid.appendChild(label);
  });

  // set default datetime to now
  const now = new Date();
  now.setSeconds(0, 0);
  document.getElementById('manualDt').value = now.toISOString().slice(0, 19);

  setupDrop();
}

// ── API HELPER ─────────────────────────────────────────────────────────────────
async function api(endpoint, body = null) {
  const opts = { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(endpoint, opts);
  return r.json();
}

// ── EXIFTOOL / FFMPEG ──────────────────────────────────────────────────────────
async function browseExiftool() {
  const res = await api('/api/browse_exiftool', {});
  if (res.ok) {
    document.getElementById('exifStatus').textContent = res.path;
    document.getElementById('exifStatus').classList.add('ok');
    toast('ExifTool saved', 'good');
  }
}

async function browseFfmpeg() {
  const res = await api('/api/browse_ffmpeg', {});
  if (res.ok) {
    document.getElementById('ffmpegStatus').innerHTML = res.path +
      ' <span style="color:var(--text3);font-size:10px;">(AVI)</span>';
    document.getElementById('ffmpegStatus').classList.add('ok');
    toast('FFmpeg saved', 'good');
  }
}

// ── FILES ──────────────────────────────────────────────────────────────────────
async function addFiles() {
  setStatus('opening file dialog…');
  const res = await api('/api/add_files', {});
  await afterFilesChanged(res.files);
}

async function addFolder() {
  setStatus('opening folder dialog…');
  const recursive = document.getElementById('optRecursive').checked;
  const res = await api('/api/add_folder', { recursive });
  await afterFilesChanged(res.files);
}

async function clearFiles() {
  await api('/api/clear_files', {});
  files = []; currentMeta = {}; previewMeta = {}; statusMap = {}; selectedPaths.clear();
  renderTable();
  setStatus('cleared');
}

async function removeSelected() {
  const paths = [...selectedPaths];
  await api('/api/remove_files', { paths });
  selectedPaths.clear();
  files = files.filter(f => !paths.includes(f.path));
  paths.forEach(p => { delete currentMeta[p]; delete previewMeta[p]; delete statusMap[p]; });
  renderTable();
}

async function afterFilesChanged(newFiles) {
  files = newFiles;
  files.forEach(f => { if (!statusMap[f.path]) statusMap[f.path] = 'ready'; });
  renderTable();
  updateFileCount();
  // async metadata read
  await loadCurrentMeta();
}

async function loadCurrentMeta() {
  if (!files.length) return;
  setStatus('reading metadata…');
  files.forEach(f => statusMap[f.path] = 'loading');
  renderTable();
  const res = await api('/api/read_metadata', { files: files.map(f => f.path) });
  // res is now path -> {value, field}
  currentMeta = { ...currentMeta, ...res };
  files.forEach(f => statusMap[f.path] = 'ready');
  renderTable();
  setStatus(`${files.length} file${files.length !== 1 ? 's' : ''} loaded`);

  // Update field filter dropdown and copy source hint
  _updateFieldFilterOptions();
  _updateCopySourceHint();
}

// ── DROP ───────────────────────────────────────────────────────────────────────
// pywebviewFullPath is ONLY available Python-side inside DOMEventHandler.
// JS File objects never have filesystem paths in pywebview's Qt backend.
// Python's on_drop() calls these globals after processing.

window.showDropOverlay = function() {
  document.getElementById('dropOverlay').classList.add('visible');
};
window.hideDropOverlay = function() {
  document.getElementById('dropOverlay').classList.remove('visible');
};
window.receiveDropResult = async function(newFiles) {
  document.getElementById('dropOverlay').classList.remove('visible');
  await afterFilesChanged(newFiles);
};

function setupDrop() {
  const zone = document.getElementById('dropZone');
  // Prevent browser default navigation on drop.
  // Visual feedback is handled by Python's DOMEventHandler calling showDropOverlay/hideDropOverlay.
  zone.addEventListener('dragover',  e => e.preventDefault());
  zone.addEventListener('dragenter', e => e.preventDefault());
  zone.addEventListener('drop',      e => e.preventDefault());
}

// ── MODE ───────────────────────────────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.querySelectorAll('.mode-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
  document.querySelectorAll('.mode-panel').forEach(p => p.classList.remove('visible'));
  document.getElementById(`panel-${mode}`).classList.add('visible');
  // clear previews when mode changes
  previewMeta = {};
  renderTable();
}

// ── PREVIEW ───────────────────────────────────────────────────────────────────
async function previewChanges() {
  if (!files.length) { toast('no files loaded', 'err'); return; }
  setStatus('computing preview…');
  const payload = buildPayload();
  payload.selected_paths = [...selectedPaths];
  const scope = selectedPaths.size > 0 ? selectedPaths.size : files.length;
  const res = await api('/api/preview', payload);
  previewMeta = { ...previewMeta, ...res };
  renderTable();
  setStatus(`preview ready for ${scope} file${scope !== 1 ? 's' : ''} — check After column`);
}

// ── APPLY ─────────────────────────────────────────────────────────────────────
async function applyChanges() {
  if (!files.length) { toast('no files loaded', 'err'); return; }
  const scope = selectedPaths.size > 0 ? selectedPaths.size : files.length;
  const scopeLabel = selectedPaths.size > 0
    ? `${scope} selected file${scope !== 1 ? 's' : ''}`
    : `all ${scope} file${scope !== 1 ? 's' : ''}`;
  setStatus(`applying to ${scopeLabel}…`);
  showProgress(true);
  setProgress(10);

  const payload = buildPayload();
  payload.touch_fs = document.getElementById('optTouchFS').checked;
  payload.win_creation = document.getElementById('optWinCreation').checked;
  payload.rename = document.getElementById('optRename').checked;
  payload.dest_fields = getDestFields();
  payload.selected_paths = [...selectedPaths];

  const res = await api('/api/apply', payload);
  setProgress(90);

  if (res.error) { toast(res.error, 'err'); showProgress(false); setStatus('error'); return; }

  // update file list (may have renamed)
  files = res.files;
  // mark statuses
  files.forEach(f => statusMap[f.path] = 'ok');
  if (res.errors && res.errors.length) {
    res.errors.forEach(e => {
      const name = e.split(':')[0];
      const f = files.find(ff => ff.name === name);
      if (f) statusMap[f.path] = 'err';
    });
  }

  // refresh metadata
  currentMeta = {};
  previewMeta = {};
  await loadCurrentMeta();

  setProgress(100);
  setTimeout(() => showProgress(false), 800);

  hasLastBatch = true;
  document.getElementById('undoBtn').disabled = false;

  const errCount = res.errors ? res.errors.length : 0;
  if (errCount > 0) {
    const firstErr = res.errors[0];
    toast(`${firstErr}`, 'err');
    setStatus(`${errCount} error${errCount > 1 ? 's' : ''}: ${res.errors.join(' | ')}`);
    console.error('Apply errors:', res.errors);
  } else {
    toast(`${scopeLabel} updated`, 'good');
    setStatus(`applied to ${scopeLabel}`);
  }
}

// ── UNDO ──────────────────────────────────────────────────────────────────────
async function undoLast() {
  if (!hasLastBatch) return;
  setStatus('undoing…');
  const res = await api('/api/undo', {});
  if (res.errors && res.errors.length) {
    toast(`undo: ${res.errors.length} errors`, 'err');
  } else {
    toast('undone', 'good');
  }
  hasLastBatch = false;
  document.getElementById('undoBtn').disabled = true;
  files.forEach(f => statusMap[f.path] = 'ready');
  currentMeta = {}; previewMeta = {};
  await loadCurrentMeta();
}

async function cleanupBackups() {
  setStatus('cleaning up backups…');
  const res = await api('/api/cleanup_backups', {});
  if (res.errors && res.errors.length) {
    toast(`cleanup: ${res.errors.length} errors`, 'err');
    setStatus(`deleted ${res.count} folder${res.count !== 1 ? 's' : ''}, ${res.errors.length} errors`);
  } else if (!res.count) {
    toast('no BACKUPS folders found', '');
    setStatus('no BACKUPS folders found');
  } else {
    toast(`BACKUPS folder${res.count !== 1 ? 's' : ''} deleted`, 'good');
    setStatus(`cleaned up ${res.count} BACKUPS folder${res.count !== 1 ? 's' : ''}`);
  }
  hasLastBatch = false;
  document.getElementById('undoBtn').disabled = true;
}

// ── BUILD PAYLOAD ─────────────────────────────────────────────────────────────
function buildPayload() {
  const p = { mode: currentMode };
  if (currentMode === 'manual') {
    let raw = document.getElementById('manualDt').value;
    // Ensure seconds are present: "2017-08-10T15:00" → "2017-08-10T15:00:00"
    if (raw.length === 16) raw = raw + ':00';
    p.datetime = raw.replace('T', ' ').replace(/-/g, ':').replace(/(\d{4}):(\d{2}):(\d{2})/, '$1:$2:$3');
  } else if (currentMode === 'copy') {
    p.source_field = document.getElementById('copySource').value;
  } else if (currentMode === 'shift') {
    p.years   = parseInt(document.getElementById('shiftYears').value) || 0;
    p.months  = parseInt(document.getElementById('shiftMonths').value) || 0;
    p.days    = parseInt(document.getElementById('shiftDays').value) || 0;
    p.hours   = parseInt(document.getElementById('shiftHours').value) || 0;
    p.minutes = parseInt(document.getElementById('shiftMins').value) || 0;
  }
  return p;
}

function getDestFields() {
  return [...document.querySelectorAll('.dest-cb:checked')].map(c => c.dataset.field);
}

// ── SELECTION ─────────────────────────────────────────────────────────────────
function toggleRow(path, cb) {
  if (cb.checked) selectedPaths.add(path);
  else selectedPaths.delete(path);
  document.querySelectorAll(`tr[data-path="${CSS.escape(path)}"]`).forEach(r => r.classList.toggle('selected', cb.checked));
  updateSelectionCount();
}

function toggleSelectAll(masterCb) {
  // Only toggles visible (filtered) rows
  document.querySelectorAll('.row-cb').forEach(cb => {
    cb.checked = masterCb.checked;
    const path = cb.closest('tr').dataset.path;
    if (masterCb.checked) selectedPaths.add(path);
    else selectedPaths.delete(path);
  });
  document.querySelectorAll('tr.file-row').forEach(r => r.classList.toggle('selected', masterCb.checked));
  updateSelectionCount();
}

// ── FIELD FILTER ──────────────────────────────────────────────────────────────
function _updateFieldFilterOptions() {
  // Collect all distinct source fields across loaded files
  const fields = new Set();
  for (const f of files) {
    const entry = currentMeta[f.path];
    if (entry?.field) fields.add(entry.field);
  }
  const sel = document.getElementById('fieldFilter');
  const current = sel.value;
  // Rebuild options
  sel.innerHTML = '<option value="">all fields</option>';
  [...fields].sort().forEach(field => {
    const count = files.filter(f => currentMeta[f.path]?.field === field).length;
    const o = document.createElement('option');
    o.value = field;
    o.textContent = `${field}  (${count})`;
    sel.appendChild(o);
  });
  // Restore selection if still valid
  if (current && [...fields].includes(current)) sel.value = current;
  // Show filter row only when files loaded
  document.getElementById('filterRow').classList.toggle('visible', files.length > 0);
}

function applyFieldFilter() {
  activeFieldFilter = document.getElementById('fieldFilter').value;
  const hasFilter = !!activeFieldFilter;
  document.getElementById('selectFilteredBtn').style.display = hasFilter ? '' : 'none';
  renderTable();
}

function selectAllFiltered() {
  // Select all rows currently visible under the active filter
  const filtered = activeFieldFilter
    ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter)
    : files;
  filtered.forEach(f => selectedPaths.add(f.path));
  renderTable();
  updateSelectionCount();
}

// ── SELECTION COUNT ───────────────────────────────────────────────────────────
function updateSelectionCount() {
  const el = document.getElementById('selCount');
  if (selectedPaths.size > 0) {
    el.textContent = `${selectedPaths.size} selected`;
    el.classList.add('visible');
  } else {
    el.classList.remove('visible');
  }
  document.getElementById('removeSelectedBtn').disabled = selectedPaths.size === 0;
}

// ── COPY SOURCE HINT ──────────────────────────────────────────────────────────
function _updateCopySourceHint() {
  // Count which field is the source for each loaded file
  const fieldCounts = {};
  for (const f of files) {
    const entry = currentMeta[f.path];
    if (entry && entry.field) {
      fieldCounts[entry.field] = (fieldCounts[entry.field] || 0) + 1;
    }
  }
  // Find the most common field
  const topField = Object.entries(fieldCounts).sort((a, b) => b[1] - a[1])[0]?.[0];

  // Update the copy source dropdown: mark each option
  const sel = document.getElementById('copySource');
  for (const opt of sel.options) {
    const count = fieldCounts[opt.value] || 0;
    if (count > 0) {
      opt.textContent = `${opt.value}  ← ${count} file${count !== 1 ? 's' : ''}`;
    } else {
      opt.textContent = opt.value;
    }
  }
  // Auto-select the most common one
  if (topField) sel.value = topField;
}

// ── RENDER TABLE ──────────────────────────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById('fileTable');
  const empty = document.getElementById('emptyState');
  const wrap  = document.getElementById('tableWrap');

  if (!files.length) {
    empty.classList.remove('hidden');
    wrap.classList.remove('visible');
    updateFileCount();
    updateSelectionCount();
    return;
  }
  empty.classList.add('hidden');
  wrap.classList.add('visible');

  // Apply field filter
  const visible = activeFieldFilter
    ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter)
    : files;

  tbody.innerHTML = visible.map(f => {
    const entry = currentMeta[f.path];
    const curVal   = entry?.value || '—';
    const curField = entry?.field || '';
    const prev = previewMeta[f.path] || '';
    const st   = statusMap[f.path] || 'ready';
    const sel  = selectedPaths.has(f.path);

    const afterCls = prev && prev !== curVal ? 'date-col after' : 'date-col no-change';
    const afterVal = prev || '—';

    const fieldLabel = curField
      ? ` <span style="color:var(--text3);font-size:10px;">(${curField})</span>`
      : '';

    const badgeMap = {
      ok:      '<span class="status-badge ok">ok</span>',
      err:     '<span class="status-badge err">err</span>',
      loading: '<span class="status-badge loading">…</span>',
      ready:   '<span class="status-badge ready">—</span>'
    };

    return `<tr class="file-row${sel ? ' selected' : ''}" data-path="${escHtml(f.path)}">
      <td style="width:32px;text-align:center;">
        <input type="checkbox" class="row-cb" ${sel ? 'checked' : ''} style="accent-color:var(--gold);width:13px;height:13px;cursor:pointer;" onclick="toggleRow('${escJs(f.path)}', this)"/>
      </td>
      <td class="name-col" title="${escHtml(f.path)}">${escHtml(f.name)}</td>
      <td class="date-col" title="${escHtml(curVal + (curField ? ' (' + curField + ')' : ''))}">${escHtml(curVal)}${fieldLabel}</td>
      <td class="${afterCls}" title="${escHtml(afterVal)}">${escHtml(afterVal)}</td>
      <td class="status-col">${badgeMap[st] || badgeMap.ready}</td>
    </tr>`;
  }).join('');

  updateFileCount();
  updateSelectionCount();
}

function updateFileCount() {
  const visible = activeFieldFilter
    ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter).length
    : files.length;
  const total = files.length;
  const el = document.getElementById('fileCount');
  if (activeFieldFilter && visible !== total) {
    el.textContent = `${visible} shown / ${total} total`;
  } else {
    el.textContent = `${total} file${total !== 1 ? 's' : ''}`;
  }
}

// ── UI HELPERS ────────────────────────────────────────────────────────────────
function setStatus(msg) { document.getElementById('statusMsg').textContent = msg; }
function showProgress(v) { document.getElementById('progressWrap').classList.toggle('visible', v); }
function setProgress(pct) { document.getElementById('progressBar').style.width = pct + '%'; }

let toastTimer;
function toast(msg, type = '') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ''; }, 2800);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escJs(s) {
  return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
}

init();
