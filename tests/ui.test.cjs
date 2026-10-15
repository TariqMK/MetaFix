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
