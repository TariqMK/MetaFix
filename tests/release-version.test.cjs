const { test } = require('node:test');
const assert = require('node:assert/strict');
const { nextVersion } = require('../scripts/release-version.cjs');

test('first release starts from zero', () => {
  assert.equal(nextVersion([], 'patch'), '0.0.1');
  assert.equal(nextVersion([], 'minor'), '0.1.0');
  assert.equal(nextVersion([], 'major'), '1.0.0');
});
test('numeric ordering and reset of lower components', () => {
  const tags = ['v1.9.9', 'v1.10.4', 'unrelated'];
  assert.equal(nextVersion(tags, 'patch'), '1.10.5');
  assert.equal(nextVersion(tags, 'minor'), '1.11.0');
  assert.equal(nextVersion(tags, 'major'), '2.0.0');
});
test('drafts and prereleases reserve their version', () => {
  assert.equal(nextVersion(['v1.0.0', 'v1.1.0', 'v2.0.0-rc.1'], 'patch'), '2.0.1');
});
test('reject unknown bump', () => assert.throws(() => nextVersion([], 'other')));
test('prepare paginates releases and tags, including an untagged draft', async () => {
  const { prepare } = require('../scripts/release-version.cjs');
  const outputs = {};
  const listReleases = Symbol('releases');
  const listTags = Symbol('tags');
  const calls = [];
  const github = {
    rest: { repos: { listReleases, listTags } },
    paginate: async (method, params) => {
      calls.push(params);
      return method === listReleases ? [{ tag_name: 'v3.2.5', draft: true }] : [{ name: 'v3.2.4' }];
    },
  };
  const summary = { addHeading() { return this; }, addTable() { return this; }, async write() {} };
  process.env.VERSION_BUMP = 'patch';
  process.env.RELEASE_VISIBILITY = 'draft';
  await prepare({ github, context: { repo: { owner: 'owner', repo: 'repo' }, sha: 'sha' }, core: { setOutput: (k,v) => outputs[k]=v, summary } });
  assert.equal(outputs.tag, 'v3.2.6');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].per_page, 100);
});
