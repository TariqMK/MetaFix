// Release tags, including draft release tag names, are the version history.

function nextVersion(names, bump) {
  if (!['major', 'minor', 'patch'].includes(bump)) throw new Error('Invalid version bump');
  const versions = names.map(name => /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.exec(name))
    .filter(Boolean).map(match => match.slice(1, 4).map(Number));
  let current = [0, 0, 0];
  for (const version of versions) {
    if (version.some(n => !Number.isSafeInteger(n))) throw new Error('Version is too large');
    for (let i = 0; i < 3; i++) {
      if (version[i] > current[i]) { current = version; break; }
      if (version[i] < current[i]) break;
    }
  }
  const index = ['major', 'minor', 'patch'].indexOf(bump);
  current[index]++;
  for (let i = index + 1; i < 3; i++) current[i] = 0;
  if (!current.every(Number.isSafeInteger)) throw new Error('Version is too large');
  return current.join('.');
}

async function prepare({ github, context, core }) {
  const repo = context.repo;
  // Authenticated releases endpoint includes drafts; /releases/latest does not.
  const releases = await github.paginate(github.rest.repos.listReleases, { ...repo, per_page: 100 });
  const tags = await github.paginate(github.rest.repos.listTags, { ...repo, per_page: 100 });
  const existing = releases.find(r => (r.body || '').includes(`<!-- metafix-release-run:${context.runId} -->`));
  const version = existing ? existing.tag_name.replace(/^v/, '') : nextVersion([...releases.map(r => r.tag_name), ...tags.map(t => t.name)], process.env.VERSION_BUMP);
  core.setOutput('version', version);
  core.setOutput('tag', `v${version}`);
  await core.summary.addHeading('Release plan')
    .addTable([['Version', 'Visibility', 'Commit'], [`v${version}`, process.env.RELEASE_VISIBILITY, context.sha]])
    .write();
}

module.exports = { nextVersion, prepare };
