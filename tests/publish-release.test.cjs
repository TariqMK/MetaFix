const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { publish } = require('../scripts/publish-release.cjs');

async function scenario({ existing = true, published = false, wrongSha = false, otherRun = false, partial = false } = {}) {
  process.env.RELEASE_TAG = 'v1.2.3';
  process.env.RELEASE_VISIBILITY = 'public';
  const names = ['MetaFix-v1.2.3-windows-x64.zip', 'MetaFix-v1.2.3-macos-arm64.zip', 'MetaFix-v1.2.3-linux-x64.tar.gz'];
  const data = Buffer.from('archive');
  const digest = `sha256:${crypto.createHash('sha256').update(data).digest('hex')}`;
  const calls = [];
  const listReleases = Symbol('releases'), listReleaseAssets = Symbol('assets');
  const release = { id: 1, tag_name:'v1.2.3', body: otherRun ? 'other' : '<!-- metafix-release-run:7 -->', draft: !published, html_url:'url' };
  const repos = { listReleases, listReleaseAssets };
  for (const name of ['createRelease','deleteReleaseAsset','uploadReleaseAsset','updateRelease']) {
    repos[name] = async args => { calls.push([name,args]); return { data: release }; };
  }
  const github = { rest: { repos, git: {
    getRef: async () => {
      if (!existing) throw Object.assign(new Error('missing'), {status:404});
      return {data:{object:{type:'commit',sha:wrongSha ? 'wrong' : 'built'}}};
    },
    createRef: async args => calls.push(['createRef',args]),
  } }, paginate: async method => method === listReleases ? (existing ? [release] : []) :
    names.slice(0, partial ? 1 : 3).map((name,id) => ({id,name,digest})) };
  const summary = { addHeading() {return this;}, addLink(){return this;}, async write(){} };
  const read = fs.readFileSync, dir = fs.readdirSync;
  fs.readFileSync = file => String(file).includes('release-assets') ? data : read(file);
  fs.readdirSync = file => file === 'release-assets' ? names : dir(file);
  try { await publish({github,context:{repo:{owner:'o',repo:'r'},sha:'built',runId:7},core:{summary}}); }
  finally { fs.readFileSync = read; fs.readdirSync = dir; }
  return calls;
}

test('resume draft skips existing verified assets', async () => {
  const calls = await scenario();
  assert.deepEqual(calls.map(([name])=>name), ['updateRelease']);
});
test('partially uploaded draft uploads only missing assets', async () => {
  const calls = await scenario({ partial:true });
  assert.equal(calls.filter(([name])=>name==='uploadReleaseAsset').length, 2);
  assert.equal(calls.filter(([name])=>name==='createRelease').length, 0);
});
test('retry of published release makes no changes', async () => assert.equal((await scenario({published:true})).length,0));
test('refuse mismatched tag commit', async () => assert.rejects(scenario({wrongSha:true}), /built commit/));
test('refuse release owned by another run', async () => assert.rejects(scenario({otherRun:true}), /different workflow run/));
test('first publication creates tag and draft before assets', async () => {
  const calls = await scenario({existing:false,partial:true});
  assert.equal(calls[0][0], 'createRef');
  assert.equal(calls[1][0], 'createRelease');
  assert.equal(calls[1][1].draft,true);
  assert.equal(calls.at(-1)[0], 'updateRelease');
});
