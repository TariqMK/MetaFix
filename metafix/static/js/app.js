
// ── STATE ──────────────────────────────────────────────────────────────────────
let files = [];         // [{path, name}]
let currentMeta = {};   // path -> {value: "2026:06:06 21:34:15", field: "CreateDate"}
let previewMeta = {};   // path -> date string
let statusMap = {};     // path -> 'ready'|'ok'|'err'|'loading'
let rowErrors = {};     // path -> message shown in that file's row
let selectedPaths = new Set();
let currentMode = 'manual';
let destFieldKeys = [];
let hasLastBatch = false;
let undoCount = 0;
let toolsMissing = false;
let copySourceChosen = false;
let activeFieldFilter = '';  // field name to filter table by, or '' for all

const ICON_CHECK = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"></path></svg>';
const ICON_ALERT = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><path d="M12 8v4"></path><path d="M12 16h.01"></path></svg>';

// ── INIT ───────────────────────────────────────────────────────────────────────
async function init() {
  const cfg = await api('/api/config');
  toolsMissing = !cfg.exiftool_path;
  if (cfg.exiftool_path) document.getElementById('exifStatus').textContent = cfg.exiftool_path;
  if (cfg.ffmpeg_path) document.getElementById('ffmpegStatus').textContent = cfg.ffmpeg_path;

  // Windows creation dates rely on PowerShell, so other platforms never offer them.
  if (!cfg.is_windows) {
    document.getElementById('optWinRow').hidden = true;
    document.getElementById('optWinCreation').checked = false;
  }

  // populate copy source
  const cs = document.getElementById('copySource');
  cfg.copy_source_fields.forEach(f => {
    const o = document.createElement('option'); o.value = f; o.textContent = f; cs.appendChild(o);
  });

  // populate dest fields
  destFieldKeys = cfg.dest_fields;
  const grid = document.getElementById('destFields');
  cfg.dest_field_groups.forEach(group => {
    const title = document.createElement('div');
    title.className = 'field-group-title';
    title.textContent = group.title;
    grid.appendChild(title);
    group.fields.forEach(f => {
      const label = document.createElement('label');
      label.className = 'checkbox-row';
      label.innerHTML = `<input type="checkbox" class="dest-cb" data-field="${f}" checked/><span class="field-name">${f}</span>`;
      grid.appendChild(label);
    });
  });

  // set default datetime to now
  const now = new Date();
  now.setSeconds(0, 0);
  document.getElementById('manualDt').value = localInputValue(now);

  setupDrop();
  updateShiftSummary();
  renderTable();
  refreshStatus();
}

// ── API HELPER ─────────────────────────────────────────────────────────────────
async function api(endpoint, body = null) {
  const opts = { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const response = await fetch(endpoint, opts);
  let result;
  try { result = await response.json(); }
  catch { throw new Error(`Server returned an unreadable response (${response.status})`); }
  if (!response.ok || result.error) {
    const details = Object.entries(result.file_errors || {}).map(([path, message]) => `${path}: ${message}`).join('; ');
    const error = new Error([result.error || `Request failed (${response.status})`, details].filter(Boolean).join(': '));
    error.fileErrors = result.file_errors;
    throw error;
  }
  return result;
}

// ── EXIFTOOL / FFMPEG ──────────────────────────────────────────────────────────
function toggleTools(event) {
  event.stopPropagation();
  setToolsOpen(document.getElementById('toolsPanel').hidden);
}

function setToolsOpen(open) {
  document.getElementById('toolsPanel').hidden = !open;
  document.getElementById('toolsBtn').ariaExpanded = String(open);
}

async function browseExiftool() {
  const res = await api('/api/browse_exiftool', {});
  if (res.ok) {
    document.getElementById('exifStatus').textContent = res.path;
    toolsMissing = false;
    updateActionState();
    setStatus('ExifTool saved', 'ok');
  }
}

async function browseFfmpeg() {
  const res = await api('/api/browse_ffmpeg', {});
  if (res.ok) {
    document.getElementById('ffmpegStatus').textContent = res.path;
    setStatus('FFmpeg saved', 'ok');
  }
}

// ── FILES ──────────────────────────────────────────────────────────────────────
async function addFiles() {
  setStatus('Opening file dialog…');
  const res = await api('/api/add_files', {});
  await afterFilesChanged(res.files);
}

async function addFolder() {
  setStatus('Opening folder dialog…');
  const recursive = document.getElementById('optRecursive').checked;
  const res = await api('/api/add_folder', { recursive });
  await afterFilesChanged(res.files);
}

async function clearFiles() {
  await api('/api/clear_files', {});
  files = []; currentMeta = {}; previewMeta = {}; statusMap = {}; rowErrors = {}; selectedPaths.clear();
  activeFieldFilter = '';
  _updateFieldFilterOptions();
  renderTable();
  refreshStatus();
}

async function removeSelected() {
  const paths = [...selectedPaths];
  await api('/api/remove_files', { paths });
  selectedPaths.clear();
  files = files.filter(f => !paths.includes(f.path));
  previewMeta = {};
  _updateFieldFilterOptions();
  paths.forEach(p => { delete currentMeta[p]; delete previewMeta[p]; delete statusMap[p]; delete rowErrors[p]; });
  renderTable();
  refreshStatus();
}

async function afterFilesChanged(newFiles) {
  previewMeta = {};
  files = newFiles;
  files.forEach(f => { if (!statusMap[f.path]) statusMap[f.path] = 'ready'; });
  renderTable();
  updateFileCount();
  // async metadata read
  await loadCurrentMeta();
  refreshStatus();
}

async function loadCurrentMeta() {
  if (!files.length) return;
  setStatus('Reading metadata…');
  files.forEach(f => { if (!['ok', 'err'].includes(statusMap[f.path])) statusMap[f.path] = 'loading'; });
  renderTable();
  const res = await api('/api/read_metadata', { files: files.map(f => f.path) });
  // res is now path -> {value, field}
  currentMeta = res;
  files.forEach(f => {
    if (res[f.path]?.error) { statusMap[f.path] = 'err'; rowErrors[f.path] = res[f.path].error; }
    else if (statusMap[f.path] === 'loading') statusMap[f.path] = 'ready';
  });
  renderTable();

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
window.receiveNativeDrop = async function(paths) {
  document.getElementById('dropOverlay').classList.remove('visible');
  if (toolsMissing) { setStatus('Choose ExifTool before adding files', 'bad'); return; }
  const result = await api('/api/drop_files', { paths, recursive: false });
  await afterFilesChanged(result.files);
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
  invalidatePreview();
}

// ── SHIFT SUMMARY ──────────────────────────────────────────────────────────────
function describeShift(shift) {
  const parts = [['years', 'year'], ['months', 'month'], ['days', 'day'], ['hours', 'hour'], ['minutes', 'minute']]
    .filter(([key]) => shift[key])
    .map(([key, unit]) => `${plural(Math.abs(shift[key]), unit)} ${shift[key] > 0 ? 'later' : 'earlier'}`);
  if (!parts.length) return 'Enter an amount to move each date';
  const last = parts.pop();
  return `Moves each date ${parts.length ? `${parts.join(', ')} and ${last}` : last}`;
}

function readShift() {
  const value = id => parseInt(document.getElementById(id).value) || 0;
  return { years: value('shiftYears'), months: value('shiftMonths'), days: value('shiftDays'),
           hours: value('shiftHours'), minutes: value('shiftMins') };
}

function updateShiftSummary() {
  document.getElementById('shiftSummary').textContent = describeShift(readShift());
}

// ── PREVIEW AND APPLY ─────────────────────────────────────────────────────────
function previewReady() { return Object.keys(previewMeta).length > 0; }

// One button previews then applies, so the second click of a double-click must not
// count as permission to write. Apply stays locked briefly after each preview.
const APPLY_UNLOCK_MS = 1000;
let applyUnlockAt = 0;

function applyLocked() { return previewReady() && Date.now() < applyUnlockAt; }

function commitChanges() {
  if (applyLocked()) return;
  return previewReady() ? applyChanges() : previewChanges();
}

function scopeWords() {
  if (selectedPaths.size > 0) return plural(selectedPaths.size, 'selected file');
  return files.length === 1 ? '1 file' : `all ${plural(files.length, 'file')}`;
}

function commitLabel() {
  if (toolsMissing) return 'Set up ExifTool first';
  if (!files.length) return 'Preview changes';
  return `${previewReady() ? 'Apply to' : 'Preview'} ${scopeWords()}`;
}

async function previewChanges() {
  if (!files.length) { setStatus('No files loaded', 'bad'); return; }
  previewMeta = {};
  clearPreviewErrors();
  renderTable();
  setStatus('Computing preview…');
  const payload = buildPayload();
  payload.dest_fields = getDestFields();
  payload.selected_paths = [...selectedPaths];
  try {
    previewMeta = await api('/api/preview', payload);
  } catch (error) {
    if (!error.fileErrors) throw error;
    rowErrors = { ...rowErrors, ...error.fileErrors };
    renderTable();
    const count = Object.keys(error.fileErrors).length;
    setStatus(`${plural(count, 'file')} can't use this edit. Nothing will be written until you change the edit or deselect them.`, 'bad');
    return;
  }
  applyUnlockAt = Date.now() + APPLY_UNLOCK_MS;
  setTimeout(updateActionState, APPLY_UNLOCK_MS);
  renderTable();
  refreshStatus();
}

async function applyChanges() {
  if (!files.length) { setStatus('No files loaded', 'bad'); return; }
  if (!previewReady()) { setStatus('Preview the changes before applying them', 'bad'); return; }
  const words = scopeWords();
  setStatus(`Applying to ${words}…`);
  showProgress(true);

  const payload = buildPayload();
  payload.touch_fs = document.getElementById('optTouchFS').checked;
  payload.win_creation = document.getElementById('optWinCreation').checked;
  payload.rename = document.getElementById('optRename').checked;
  payload.replace_name = document.getElementById('optReplaceName').checked;
  payload.dest_fields = getDestFields();
  payload.selected_paths = [...selectedPaths];

  const res = await api('/api/apply', payload);

  remapPaths(res.renamed || {});
  files = res.files;
  rowErrors = {};
  let updated = 0;
  for (const [path, result] of Object.entries(res.results || {})) {
    const current = result.current || path;
    statusMap[current] = result.ok ? 'ok' : 'err';
    if (result.ok) updated += 1;
    else rowErrors[current] = result.error;
  }
  setUndo(res);

  // refresh metadata
  currentMeta = {};
  previewMeta = {};
  await loadCurrentMeta();

  const errCount = res.errors ? res.errors.length : 0;
  if (errCount > 0) {
    console.error('Apply errors:', res.errors);
    setStatus(`${plural(updated, 'file')} updated, ${errCount} with errors. See the highlighted rows.`, 'bad');
  } else {
    setStatus(`${plural(updated, 'file')} updated. Originals are in the BACKUPS folder beside each file.`, 'ok');
  }
}

// ── UNDO ──────────────────────────────────────────────────────────────────────
function setUndo(res) {
  hasLastBatch = res.can_undo;
  undoCount = res.undo_count || 0;
  updateActionState();
}

async function undoLast() {
  if (!hasLastBatch) return;
  setStatus('Undoing…');
  const res = await api('/api/undo', {});
  remapPaths(res.renamed || {});
  files = res.files;
  setUndo(res);
  rowErrors = {};
  files.forEach(f => {
    statusMap[f.path] = res.file_errors?.[f.path] ? 'err' : 'ready';
    if (res.file_errors?.[f.path]) rowErrors[f.path] = res.file_errors[f.path];
  });
  currentMeta = {}; previewMeta = {};
  await loadCurrentMeta();
  if (res.errors.length) setStatus(`${plural(res.errors.length, 'file')} could not be restored. You can try undo again.`, 'bad');
  else if (res.warnings?.length) {
    console.error('Undo warnings:', res.warnings);
    setStatus(`Original files and names are back, but the created date could not be reset on ${plural(res.warnings.length, 'file')}.`, 'bad');
  }
  else setStatus('Undo complete. Original files, names and dates are back.', 'ok');
}

function confirmCleanup(backups) {
  const dialog = document.getElementById('cleanupDialog');
  const list = document.getElementById('cleanupList');
  const words = `${plural(backups.length, 'backup')}`;
  document.getElementById('cleanupTitle').textContent = `Delete ${words}?`;
  document.getElementById('cleanupConfirm').textContent = `Delete ${words}`;
  list.innerHTML = backups.map(path => `<div>${escHtml(path)}</div>`).join('');
  dialog.returnValue = 'keep';
  dialog.showModal();
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'delete'), { once: true });
  });
}

async function cleanupBackups() {
  const plan = await api('/api/cleanup_backups', {});
  if (!plan.count) { setStatus('No tracked MetaFix backups found'); return; }
  if (!await confirmCleanup(plan.backups)) return;
  const result = await api('/api/cleanup_backups', { confirm_paths: plan.backups });
  if (result.confirmation_required) throw new Error('Backup list changed; review cleanup again');
  setUndo(result);
  setStatus(`Deleted ${plural(result.count, 'backup')}`, 'ok');
  if (result.errors.length) throw new Error(result.errors.join('; '));
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
    Object.assign(p, readShift());
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
  invalidatePreview();
  updateSelectionCount();
}

function toggleSelectAll(masterCb) {
  previewMeta = {};
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
  sel.innerHTML = '<option value="">All sources</option>';
  [...fields].sort().forEach(field => {
    const count = files.filter(f => currentMeta[f.path]?.field === field).length;
    const o = document.createElement('option');
    o.value = field;
    o.textContent = `${field} (${count})`;
    sel.appendChild(o);
  });
  // Keep UI filter and stored filter synchronized after refresh.
  if (current && [...fields].includes(current)) sel.value = current;
  activeFieldFilter = sel.value;
  // Show filter only when files loaded
  document.getElementById('filterRow').classList.toggle('visible', files.length > 0);
  updateActionState();
}

function applyFieldFilter() {
  activeFieldFilter = document.getElementById('fieldFilter').value;
  renderTable();
  refreshStatus();
}

function selectAllFiltered() {
  // Select all rows currently visible under the active filter
  const filtered = activeFieldFilter
    ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter)
    : files;
  filtered.forEach(f => selectedPaths.add(f.path));
  invalidatePreview();
  updateSelectionCount();
}

// ── SELECTION COUNT ───────────────────────────────────────────────────────────
function updateSelectionCount() {
  updateFileCount();
  updateActionState();
}

function updateActionState() {
  const selected = selectedPaths.size > 0;
  const remove = document.getElementById('removeSelectedBtn');
  remove.style.display = selected ? '' : 'none';
  remove.disabled = window.metafixBusy || !selected;
  document.getElementById('clearBtn').style.display = !selected && files.length ? '' : 'none';
  document.getElementById('selectFilteredBtn').style.display = activeFieldFilter ? '' : 'none';

  const commit = document.getElementById('commitBtn');
  commit.textContent = commitLabel();
  commit.disabled = window.metafixBusy || toolsMissing || !files.length || applyLocked();

  document.getElementById('undoBtn').disabled = window.metafixBusy || !hasLastBatch;
  document.getElementById('undoLabel').textContent = hasLastBatch && undoCount
    ? `Undo ${plural(undoCount, 'edit')}` : 'Undo';

  document.getElementById('toolsLabel').textContent = toolsMissing ? 'Set up ExifTool' : 'Tools';
  document.getElementById('toolsNotice').hidden = !toolsMissing;
  document.querySelectorAll('.add-btn').forEach(button => { button.disabled = window.metafixBusy || toolsMissing; });

  const scope = selectedPaths.size > 0 ? files.filter(f => selectedPaths.has(f.path)) : files;
  document.getElementById('aviNote').style.display = scope.some(f => /\.avi$/i.test(f.path)) ? '' : 'none';
  document.getElementById('renameNote').style.display = document.getElementById('optRename').checked ? '' : 'none';
  document.getElementById('renameNote').textContent = document.getElementById('optReplaceName').checked
    ? 'Replaces the name, like 2019-06-15_14-07-32.jpg'
    : 'Adds a prefix, like 2019-06-15_14-07-32_photo.jpg';
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
    opt.textContent = count > 0 ? `${opt.value} (${count})` : opt.value;
  }
  // Auto-select the most common one
  const available = [...sel.options].map(option => option.value);
  if (!copySourceChosen && topField && available.includes(topField)) sel.value = topField;
}

// ── DATES ─────────────────────────────────────────────────────────────────────
// Offset-aware values become local wall-clock time, matching how edits are planned.
function normalizeDate(value) {
  const match = /^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$/.exec(String(value ?? '').trim());
  if (!match) return null;
  const [, year, month, day, hour, minute, second, zone] = match;
  if (!zone) return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
  const date = new Date(`${year}-${month}-${day}T${hour}:${minute}:${second}${zone}`);
  return localInputValue(date).replace('T', ' ');
}

function dateDiffHtml(before, after) {
  const newDate = normalizeDate(after);
  if (!newDate) return escHtml(after);
  const oldParts = (normalizeDate(before) || '').split(/([-: ])/);
  return newDate.split(/([-: ])/).map((part, i) => {
    const changed = /\d/.test(part) && part !== oldParts[i];
    return `<span class="dp${changed ? ' changed' : ''}">${escHtml(part)}</span>`;
  }).join('');
}

function newDateCell(path, curVal) {
  if (rowErrors[path]) return `<span class="row-error" title="${escHtml(rowErrors[path])}">${escHtml(rowErrors[path])}</span>`;
  const next = previewMeta[path];
  if (!next) return '<span class="no-date">—</span>';
  // The date can match while fields still differ, so "same" never means nothing is written.
  if (normalizeDate(next) === normalizeDate(curVal)) return '<span class="no-date">Same date</span>';
  return dateDiffHtml(curVal, next);
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
    const st   = statusMap[f.path] || 'ready';
    const sel  = selectedPaths.has(f.path);

    const sourceNote = curField.startsWith('File') ? ' · file system' : '';

    const badgeMap = {
      ok:      `<span class="status-badge ok">${ICON_CHECK}Updated</span>`,
      err:     `<span class="status-badge err">${ICON_ALERT}Error</span>`,
      loading: '<span class="status-badge loading">Reading…</span>',
      ready:   ''
    };

    return `<tr class="file-row${sel ? ' selected' : ''}" data-path="${escHtml(f.path)}">
      <td class="box-col">
        <input type="checkbox" class="row-cb" aria-label="Select ${escHtml(f.name)}" ${window.metafixBusy ? 'disabled' : ''} ${sel ? 'checked' : ''}/>
      </td>
      <td class="name-col" title="${escHtml(f.path)}">${escHtml(f.name)}</td>
      <td class="date-col" title="${escHtml(curVal)}">${escHtml(normalizeDate(curVal) || curVal)}</td>
      <td class="source-col" title="${escHtml(curField + sourceNote)}"><span class="field-name">${escHtml(curField)}</span>${sourceNote}</td>
      <td class="date-col">${newDateCell(f.path, curVal)}</td>
      <td class="status-col">${badgeMap[st] ?? badgeMap.ready}</td>
    </tr>`;
  }).join('');

  const master = document.querySelector('thead input[type="checkbox"]');
  if (master) {
    const count = visible.filter(f => selectedPaths.has(f.path)).length;
    master.checked = visible.length > 0 && count === visible.length;
    master.indeterminate = count > 0 && count < visible.length;
  }
  updateFileCount();
  updateSelectionCount();
}

function updateFileCount() {
  const visible = activeFieldFilter
    ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter).length
    : files.length;
  const total = files.length;
  const parts = [];
  if (total) parts.push(activeFieldFilter && visible !== total ? `${visible} shown of ${plural(total, 'file')}` : plural(total, 'file'));
  if (selectedPaths.size) parts.push(`${selectedPaths.size} selected`);
  document.getElementById('fileCount').textContent = parts.join(' · ');
}

// ── UI HELPERS ────────────────────────────────────────────────────────────────
function plural(count, word) { return `${count} ${word}${count === 1 ? '' : 's'}`; }

function setStatus(msg, kind = '') {
  document.getElementById('statusMsg').textContent = msg;
  document.getElementById('summary').className = `summary${kind ? ' ' + kind : ''}${msg ? '' : ' gone'}`;
}

// The guidance shown whenever no result or error needs to stay on screen.
function refreshStatus() {
  if (!files.length) { setStatus(''); return; }
  if (!previewReady()) { setStatus('Choose an edit, then preview it. Nothing is written until you apply.'); return; }
  const count = Object.keys(previewMeta).length;
  const shown = activeFieldFilter ? files.filter(f => currentMeta[f.path]?.field === activeFieldFilter).length : files.length;
  const hidden = !selectedPaths.size ? files.length - shown : 0;
  setStatus(`${plural(count, 'file')} ready to write. Nothing has been written yet.${hidden ? ` Includes ${plural(hidden, 'file')} hidden by the filter.` : ''}`);
}

function showProgress(v) { document.getElementById('progressWrap').classList.toggle('visible', v); }

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function localInputValue(date) {
  const pad = value => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

// Preview errors go stale with their inputs; failed writes stay until the next action.
function clearPreviewErrors() {
  for (const path of Object.keys(rowErrors)) {
    if (statusMap[path] !== 'err') delete rowErrors[path];
  }
}

function invalidatePreview() {
  previewMeta = {};
  clearPreviewErrors();
  renderTable();
  refreshStatus();
}
function remapPaths(renamed) {
  selectedPaths = new Set([...selectedPaths].map(path => renamed[path] || path));
  for (const [oldPath, newPath] of Object.entries(renamed)) {
    if (statusMap[oldPath]) statusMap[newPath] = statusMap[oldPath];
    delete statusMap[oldPath];
  }
  previewMeta = {};
}

window.metafixBusy = false;
function guarded(action) {
  return async function(...args) {
    if (window.metafixBusy) return;
    window.metafixBusy = true;
    const controls = [...document.querySelectorAll('button:not([data-modal]), input, select')];
    const disabled = controls.map(control => control.disabled);
    controls.forEach(control => control.disabled = true);
    try { return await action(...args); }
    catch (error) { setStatus(error.message, 'bad'); }
    finally {
      window.metafixBusy = false;
      controls.forEach((control, i) => control.disabled = disabled[i]);
      document.querySelectorAll('.row-cb').forEach(control => control.disabled = false);
      updateSelectionCount();
      showProgress(false);
    }
  };
}
for (const name of ['browseExiftool', 'browseFfmpeg', 'addFiles', 'addFolder', 'clearFiles',
                    'removeSelected', 'previewChanges', 'applyChanges', 'undoLast', 'cleanupBackups']) {
  window[name] = guarded(window[name]);
}
window.receiveNativeDrop = guarded(window.receiveNativeDrop);
document.addEventListener('change', event => {
  if (event.target.classList.contains('row-cb')) {
    toggleRow(event.target.closest('tr').dataset.path, event.target);
  }
  if (event.target.id === 'copySource') copySourceChosen = true;
  // Filtering and folder scanning don't alter what a preview would write.
  if (event.target.matches('input, select') && !event.target.matches('#fieldFilter, #optRecursive')) invalidatePreview();
});
document.addEventListener('input', event => {
  if (event.target.matches('input:not([type="checkbox"])')) {
    updateShiftSummary();
    invalidatePreview();
  }
});
document.addEventListener('click', event => {
  if (!event.target.closest('#toolsPanel')) setToolsOpen(false);
  // Clicking anywhere on a row selects it, unless the click was finishing a text selection.
  const row = event.target.closest('tr.file-row');
  if (!row || event.target.matches('input') || !window.getSelection().isCollapsed) return;
  const checkbox = row.querySelector('.row-cb');
  if (checkbox.disabled) return;
  checkbox.checked = !checkbox.checked;
  toggleRow(row.dataset.path, checkbox);
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') setToolsOpen(false);
  // A held key repeats, which must not walk the main button from preview into apply.
  if (event.repeat && event.target.id === 'commitBtn') event.preventDefault();
});
guarded(init)();
