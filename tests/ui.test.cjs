const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function ui() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      disabled: false, textContent: '', className: '', innerHTML: '', style: {},
      classList: { add() {}, remove() {}, toggle() {} },
    });
    return elements.get(id);
  }
  const sandbox = { console, setTimeout, clearTimeout, CSS: { escape: s => s },
    document: { getElementById: element, querySelectorAll: () => [], querySelector: () => null, addEventListener() {} },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  const source = fs.readFileSync('metafix/static/js/app.js', 'utf8').replace('guarded(init)();', '');
  vm.runInContext(source, sandbox);
  vm.runInContext('renderTable = () => {};', sandbox);
  return { sandbox, run: code => vm.runInContext(code, sandbox), element };
}

test('manual datetime uses local components rather than UTC', () => {
  const { run, sandbox } = ui();
  sandbox.date = { getFullYear: () => 2024, getMonth: () => 5, getDate: () => 1,
    getHours: () => 14, getMinutes: () => 3, getSeconds: () => 0,
    toISOString: () => { throw new Error('must not use UTC'); } };
  assert.equal(run('localInputValue(date)'), '2024-06-01T14:03:00');
});
test('renaming remaps selection and clears stale preview', () => {
  const { run } = ui();
  run("selectedPaths = new Set(['old.jpg']); statusMap = {'old.jpg':'err'}; previewMeta={'old.jpg':'stale'}; remapPaths({'old.jpg':'new.jpg'});");
  assert.equal(run("selectedPaths.has('new.jpg')"), true);
  assert.equal(run("statusMap['new.jpg']"), 'err');
  assert.equal(run('Object.keys(previewMeta).length'), 0);
});
test('guard restores controls and clears progress after network failure', async () => {
  const { run, element } = ui();
  await run("guarded(async () => { throw new Error('Network failed'); })()");
  assert.equal(run('window.metafixBusy'), false);
  assert.equal(element('statusMsg').textContent, 'Network failed');
});
test('API rejects failed JSON and non-JSON responses', async () => {
  const { run, sandbox } = ui();
  sandbox.fetch = async () => ({ ok: false, status: 409, json: async () => ({ error: 'Busy' }) });
  await assert.rejects(run("api('/api/apply', {})"), /Busy/);
  sandbox.fetch = async () => ({ ok: false, status: 500, json: async () => { throw new Error('HTML'); } });
  await assert.rejects(run("api('/api/apply', {})"), /unreadable response/);
});
test('metadata refresh preserves operation error badges', async () => {
  const { run, sandbox } = ui();
  sandbox.fetch = async () => ({ ok: true, status: 200, json: async () => ({ 'a.jpg': { value:'2024:01:01 12:00:00', field:'CreateDate' } }) });
  run("files=[{path:'a.jpg',name:'a.jpg'}]; statusMap={'a.jpg':'err'}; _updateFieldFilterOptions=()=>{}; _updateCopySourceHint=()=>{};");
  await run('loadCurrentMeta()');
  assert.equal(run("statusMap['a.jpg']"), 'err');
});
test('copy hint cannot select a nonexistent option or override explicit choice', () => {
  const { run, element } = ui();
  const select = element('copySource');
  select.options = [{ value:'CreateDate' }];
  select.value = 'CreateDate';
  run("files=[{path:'a.jpg'}]; currentMeta={'a.jpg':{field:'unknown'}}; _updateCopySourceHint();");
  assert.equal(select.value, 'CreateDate');
  run("copySourceChosen=true; currentMeta={'a.jpg':{field:'CreateDate'}};");
  select.value = 'user-choice';
  run('_updateCopySourceHint()');
  assert.equal(select.value, 'user-choice');
});
test('preview replaces previous subset instead of merging stale entries', async () => {
  const { run, sandbox } = ui();
  sandbox.fetch = async () => ({ ok:true, status:200, json:async () => ({ 'b.jpg':'new' }) });
  run("files=[{path:'b.jpg'}]; previewMeta={'a.jpg':'old'}; selectedPaths=new Set(['b.jpg']); buildPayload=()=>({});");
  await run('previewChanges()');
  assert.equal(run("previewMeta['a.jpg']"), undefined);
  assert.equal(run("previewMeta['b.jpg']"), 'new');
});

test('failed preview clears previous results', async () => {
  const { run, sandbox } = ui();
  sandbox.fetch = async () => ({ ok:false, status:400, json:async () => ({error:'Invalid date'}) });
  run("files=[{path:'a.jpg'}]; previewMeta={'a.jpg':'stale'}; buildPayload=()=>({});");
  await run('previewChanges()');
  assert.equal(run("document.getElementById('statusMsg').textContent"), 'Invalid date');
  assert.equal(run('Object.keys(previewMeta).length'),0);
});

test('shift summary spells out mixed directions', () => {
  const { run } = ui();
  assert.equal(run('describeShift({days:1, hours:-2})'), 'Moves each date 1 day later and 2 hours earlier');
  assert.equal(run('describeShift({years:-1, months:3, minutes:30})'), 'Moves each date 1 year earlier, 3 months later and 30 minutes later');
  assert.equal(run('describeShift({})'), 'Enter an amount to move each date');
});
test('mixed shift values reach the API with their own signs', () => {
  const { run, element } = ui();
  element('shiftDays').value = '1';
  element('shiftHours').value = '-2';
  run("currentMode='shift';");
  const payload = run('buildPayload()');
  assert.equal(payload.days, 1);
  assert.equal(payload.hours, -2);
  assert.equal(payload.years, 0);
});
test('main button previews first, then names what it will apply to', () => {
  const { run } = ui();
  run("files=[{path:'a.jpg'},{path:'b.jpg'}];");
  assert.equal(run('commitLabel()'), 'Preview all 2 files');
  run("previewMeta={'a.jpg':'2024:01:01 12:00:00'}; selectedPaths=new Set(['a.jpg']);");
  assert.equal(run('commitLabel()'), 'Apply to 1 selected file');
});
test('apply refuses to run without a current preview', async () => {
  const { run, sandbox, element } = ui();
  let called = false;
  sandbox.fetch = async () => { called = true; return { ok:true, status:200, json:async () => ({}) }; };
  run("files=[{path:'a.jpg'}]; previewMeta={};");
  await run('applyChanges()');
  assert.equal(called, false);
  assert.match(element('statusMsg').textContent, /Preview the changes/);
});
test('missing ExifTool blocks the main button and dropped files', async () => {
  const { run, sandbox, element } = ui();
  let called = false;
  sandbox.fetch = async () => { called = true; return { ok:true, status:200, json:async () => ({ files:[] }) }; };
  run("toolsMissing=true; files=[{path:'a.jpg'}]; updateActionState();");
  assert.equal(element('commitBtn').disabled, true);
  await run("window.receiveNativeDrop(['a.jpg'])");
  assert.equal(called, false);
  assert.match(element('statusMsg').textContent, /Choose ExifTool/);
});
test('date diff marks only the parts that change', () => {
  const { run } = ui();
  const html = run("dateDiffHtml('2019:06:15 13:07:32', '2019:06:15 14:07:32')");
  assert.equal(html.match(/dp changed/g).length, 1);
  assert.match(html, /<span class="dp changed">14<\/span>/);
});
test('offset dates compare as local time and matching dates stay writable', () => {
  const { run } = ui();
  run("toolsMissing=false; files=[{path:'a.jpg'}]; previewMeta={'a.jpg':'2024:01:01 12:00:00'}; updateActionState();");
  assert.equal(run("normalizeDate('2024:01:01 12:00:00.5')"), '2024-01-01 12:00:00');
  assert.equal(run("normalizeDate('not a date')"), null);
  assert.match(run("newDateCell('a.jpg', '2024:01:01 12:00:00')"), /Same date/);
  // Copy mode can match the shown date while still filling other fields.
  assert.equal(run("document.getElementById('commitBtn').disabled"), false);
});
test('undo reports a created date it could not reset', async () => {
  const { run, sandbox, element } = ui();
  sandbox.fetch = async () => ({ ok:true, status:200, json:async () => ({ renamed:{}, files:[], can_undo:false, undo_count:0, errors:[], file_errors:{}, warnings:['a.jpg: failed'] }) });
  run('hasLastBatch=true;');
  await run('undoLast()');
  assert.match(element('statusMsg').textContent, /created date could not be reset on 1 file/);
});
test('per-file preview errors appear in their rows', async () => {
  const { run, sandbox, element } = ui();
  sandbox.fetch = async () => ({ ok:false, status:400, json:async () => ({ error:'Batch validation failed; no files changed', file_errors:{ 'a.jpg':'Source field CreateDate is empty' } }) });
  run("files=[{path:'a.jpg'}]; buildPayload=()=>({});");
  await run('previewChanges()');
  assert.match(run("newDateCell('a.jpg', '—')"), /Source field CreateDate is empty/);
  assert.match(element('statusMsg').textContent, /1 file can't use this edit/);
});
