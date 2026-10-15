const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function publish({ github, context, core }) {
  const repo = context.repo;
  const tag = process.env.RELEASE_TAG;
  const marker = `<!-- metafix-release-run:${context.runId} -->`;
  const names = fs.readdirSync('release-assets');
  const expected = ['windows-x64.zip', 'macos-arm64.zip', 'linux-x64.tar.gz']
    .map(suffix => `MetaFix-${tag}-${suffix}`);
  if (names.length !== 3 || expected.some(name => !names.includes(name))) {
    throw new Error('Expected exactly the three versioned platform archives');
  }
  let ref;
  try { ref = (await github.rest.git.getRef({ ...repo, ref: `tags/${tag}` })).data; }
  catch (error) { if (error.status !== 404) throw error; }
  if (ref) {
    if (ref.object.type !== 'commit' || ref.object.sha !== context.sha) {
      throw new Error('Existing release tag does not point to the built commit');
    }
  } else {
    await github.rest.git.createRef({ ...repo, ref: `refs/tags/${tag}`, sha: context.sha });
  }
  const releases = await github.paginate(github.rest.repos.listReleases, { ...repo, per_page: 100 });
  let release = releases.find(item => item.tag_name === tag);
  if (release && !(release.body || '').includes(marker)) {
    throw new Error('Existing release belongs to a different workflow run');
  }
  if (!release) {
    release = (await github.rest.repos.createRelease({
      ...repo, tag_name: tag, target_commitish: context.sha, name: `MetaFix ${tag}`,
      draft: true, prerelease: false, body: marker, generate_release_notes: true,
    })).data;
  }
  const assets = await github.paginate(github.rest.repos.listReleaseAssets, {
    ...repo, release_id: release.id, per_page: 100,
  });
  for (const name of expected) {
    const data = fs.readFileSync(path.join('release-assets', name));
    const digest = `sha256:${crypto.createHash('sha256').update(data).digest('hex')}`;
    const existing = assets.find(asset => asset.name === name);
    if (existing && existing.digest === digest) continue;
    if (!release.draft) throw new Error(`Published asset cannot be replaced: ${name}`);
    if (existing) await github.rest.repos.deleteReleaseAsset({ ...repo, asset_id: existing.id });
    await github.rest.repos.uploadReleaseAsset({ ...repo, release_id: release.id, name, data });
  }
  if (process.env.RELEASE_VISIBILITY === 'public' && release.draft) {
    release = (await github.rest.repos.updateRelease({ ...repo, release_id: release.id, draft: false })).data;
  }
  await core.summary.addHeading(`MetaFix ${tag}`).addLink('View release', release.html_url).write();
}

module.exports = { publish };
