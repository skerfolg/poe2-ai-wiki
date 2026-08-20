// Workflow Governance Kit — release composition library.
//
// Implements the §7.1 Operational Contract from docs/WORKFLOW-GOVERNANCE.md:
// given the kit's current docs (HISTORY-MAP.md, CURRENT-PLAN.md), the current
// package.json, and a version decision (literal or bump level), produce the
// post-release state of those three files plus a structured plan summary the
// CLI can print under --check or apply under --write.
//
// Inputs and outputs are pure strings; filesystem I/O is the caller's job.
// This keeps the unit-tests easy and the CLI thin.

import { SchemaError } from './task-graph-schema.mjs';

const SEMVER_RE = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/;
const VALID_BUMPS = new Set(['major', 'minor', 'patch']);

export class ReleaseComposeError extends Error {
  constructor(message, { code = 'compose-error' } = {}) {
    super(message);
    this.name = 'ReleaseComposeError';
    this.code = code;
  }
}

export function parseSemver(version) {
  const m = SEMVER_RE.exec(String(version || '').trim());
  if (!m) throw new ReleaseComposeError(`invalid semver: ${JSON.stringify(version)}`, { code: 'invalid-semver' });
  return { major: Number(m[1]), minor: Number(m[2]), patch: Number(m[3]), prerelease: m[4] || null };
}

export function formatSemver({ major, minor, patch, prerelease }) {
  const core = `${major}.${minor}.${patch}`;
  return prerelease ? `${core}-${prerelease}` : core;
}

// §7.2 Version-Decision Rules. Pre-1.0 (0.x.y): minor bump is the default
// for any lane-absorbing release; patch is for fix-only; 1.0 cutover is
// explicit via --version. 1.0+: strict semver.
export function computeNextVersion(previousVersion, { bump = 'minor', version = null } = {}) {
  if (version) {
    parseSemver(version); // validate
    return version;
  }
  if (!VALID_BUMPS.has(bump)) {
    throw new ReleaseComposeError(`unknown bump level: ${JSON.stringify(bump)} (expected: major, minor, patch)`, { code: 'invalid-bump' });
  }
  const prev = parseSemver(previousVersion);
  if (prev.prerelease) {
    // A bump from a prerelease drops the prerelease and applies the bump to the core.
    if (bump === 'major') return formatSemver({ major: prev.major + 1, minor: 0, patch: 0 });
    if (bump === 'minor') return formatSemver({ major: prev.major, minor: prev.minor + 1, patch: 0 });
    return formatSemver({ major: prev.major, minor: prev.minor, patch: prev.patch + 1 });
  }
  if (prev.major === 0) {
    // Pre-1.0 rules.
    if (bump === 'major') {
      // No-op on pre-1.0: a "major" bump in 0.x means the 1.0 cutover, which
      // must be explicit via --version 1.0.0 to avoid accidental cutovers.
      throw new ReleaseComposeError(
        `--bump major is reserved for the 1.0.0 cutover on a pre-1.0 kit (current: ${previousVersion}). Pass --version 1.0.0 explicitly when the kit is ready.`,
        { code: 'major-bump-rejected' },
      );
    }
    if (bump === 'minor') return formatSemver({ major: 0, minor: prev.minor + 1, patch: 0 });
    return formatSemver({ major: 0, minor: prev.minor, patch: prev.patch + 1 });
  }
  // 1.0+ strict semver.
  if (bump === 'major') return formatSemver({ major: prev.major + 1, minor: 0, patch: 0 });
  if (bump === 'minor') return formatSemver({ major: prev.major, minor: prev.minor + 1, patch: 0 });
  return formatSemver({ major: prev.major, minor: prev.minor, patch: prev.patch + 1 });
}

// Parses the `## Unreleased Workflow Evidence` section in HISTORY-MAP.md.
// Returns {lanes, diagnostics}: lanes is a list of {name, archivePath, line,
// summary}; diagnostics is a list of human-readable hints surfaced when the
// section was found but no bullets matched the expected markdown-link form.
// The legacy single-list return shape is preserved as the default (most
// callers spread the result), so existing usage continues to work via the
// helper signature.
export function discoverClosedLanes(historyMapText, { includeDiagnostics = false } = {}) {
  const sectionRe = /^##\s+(?:Closed Lanes(?:\s+—\s+Unreleased Evidence)?|Unreleased Workflow Evidence)\s*$/m;
  const match = sectionRe.exec(historyMapText);
  if (!match) {
    return includeDiagnostics ? { lanes: [], diagnostics: [] } : [];
  }
  // Section body extends from after the heading to the next "## " heading.
  const start = match.index + match[0].length;
  const tail = historyMapText.slice(start);
  const nextMatch = /^##\s/m.exec(tail);
  const sectionBody = nextMatch ? tail.slice(0, nextMatch.index) : tail;
  const bulletRe = /^-\s+([A-Za-z0-9][A-Za-z0-9-]*)\s+closure archive:\s*\[`([^`]+)`\]\(([^)]+)\)\.\s*(.*?)\s*$/gm;
  const lanes = [];
  let m;
  while ((m = bulletRe.exec(sectionBody)) !== null) {
    lanes.push({
      name: m[1],
      archivePath: m[2],
      archiveLink: m[3],
      summary: m[4] || '',
      line: m[0],
    });
  }
  const diagnostics = [];
  if (lanes.length === 0) {
    // The heading is present but no bullets matched. Surface the first
    // non-empty bullet-like line as a hint so the operator can correct
    // the formatting rather than puzzling over a 'no lanes' error.
    const candidateLine = sectionBody
      .split(/\r?\n/)
      .find((line) => /^(?:-|\*)\s+\S/.test(line));
    if (candidateLine) {
      diagnostics.push(
        `Unreleased Workflow Evidence section was found, but no bullets matched the expected form '- <lane-name> closure archive: [\`<path>\`](<link>). <summary>'. First non-matching bullet: ${JSON.stringify(candidateLine)}. Fix the bullet form or close the section if no lanes are pending.`,
      );
    }
  } else {
    // Code-reviewer HIGH-3: also surface lines that look like a closure-archive
    // bullet (contain the literal 'closure archive:') but did not match — they
    // are most likely malformed entries the user expected to absorb.
    //
    // Trim both sides when comparing. The bullet regex uses /m + $, so on
    // CRLF inputs `m[0]` ends with a literal \r that the per-line split() +
    // `.trim()` strips. Without normalization, every matched bullet would
    // also appear as a straggler — surfaced by the BI-self-application F5
    // dogfood run of `release compose --version 0.1.0 --check` against the
    // kit's own HISTORY-MAP.
    const matchedLines = new Set(lanes.map((l) => l.line.trim()));
    const stragglers = sectionBody
      .split(/\r?\n/)
      .filter((line) => /closure archive:/i.test(line) && !matchedLines.has(line.trim()) && /^(?:-|\*)\s+/.test(line.trim()));
    for (const line of stragglers) {
      diagnostics.push(
        `Bullet contains 'closure archive:' but did not match the expected form (missing trailing period, non-backtick path, or alternate link syntax): ${JSON.stringify(line)}.`,
      );
    }
  }
  return includeDiagnostics ? { lanes, diagnostics } : lanes;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

// Builds a new `### vX.Y.Z` entry block. Returns the markdown text (with
// trailing blank line) ready to be inserted under `## Timeline`.
function buildReleaseEntry({ version, lanes, date }) {
  const milestones = lanes.map((l) => l.name).join(', ');
  const summary = lanes.length === 0
    ? 'Maintenance release; no lane absorbed.'
    : `Composes ${lanes.length} closed lane(s) into the v${version} release.`;
  const lines = [];
  lines.push(`### v${version}`);
  lines.push('');
  lines.push(`Status: \`released ${date}\``);
  lines.push('');
  lines.push('Summary:');
  lines.push(`- ${summary}`);
  for (const lane of lanes) {
    lines.push(`- Absorbed \`${lane.name}\` — see [\`${lane.archivePath}\`](${lane.archiveLink}).`);
  }
  lines.push('');
  lines.push(`Composed milestones: ${milestones || '(none)'}`);
  lines.push('');
  return lines.join('\n');
}

// Inserts the new release entry into HISTORY-MAP.md immediately after the
// `## Timeline` Mermaid block, before any existing `### vX.Y.Z` entry, and
// removes the absorbed lanes from `## Unreleased Workflow Evidence`. Also
// touches the Mermaid timeline graph to mark absorbed lanes as released.
export function updateHistoryMap(text, { version, lanes, date }) {
  let next = text;

  // 1. Insertion point: end of the `## Timeline` fenced code block. Accept
  // both backtick (```) and tilde (~~~) fences (CommonMark) so consumers
  // whose HISTORY-MAP uses the tilde form do not silently fail with a
  // misleading 'missing-timeline' error. Code-reviewer HIGH-4.
  const timelineRe = /(^##\s+Timeline\s*$[\s\S]*?^(?:```|~~~)mermaid[\s\S]*?^(?:```|~~~)\s*$)/m;
  const tm = timelineRe.exec(next);
  if (!tm) {
    throw new ReleaseComposeError(
      'HISTORY-MAP.md: could not locate `## Timeline` Mermaid block (expected a fenced ```mermaid or ~~~mermaid block under the `## Timeline` heading)',
      { code: 'missing-timeline' },
    );
  }
  const releaseEntry = buildReleaseEntry({ version, lanes, date });
  const before = next.slice(0, tm.index + tm[0].length);
  const after = next.slice(tm.index + tm[0].length);
  next = `${before}\n\n${releaseEntry}${after}`;

  // 2. Remove absorbed lanes from `## Unreleased Workflow Evidence` section.
  //    We rebuild the section: drop bullets whose name matches an absorbed lane.
  const sectionRe = /(^##\s+(?:Closed Lanes(?:\s+—\s+Unreleased Evidence)?|Unreleased Workflow Evidence)\s*$)([\s\S]*?)(?=^##\s)/m;
  const ms = sectionRe.exec(next);
  if (ms) {
    const heading = ms[1];
    const body = ms[2];
    const absorbedNames = new Set(lanes.map((l) => l.name));
    const filteredBody = body
      .split(/\r?\n/)
      .filter((line) => {
        const bullet = /^-\s+([A-Za-z0-9][A-Za-z0-9-]*)\s+closure archive:/.exec(line);
        if (!bullet) return true;
        return !absorbedNames.has(bullet[1]);
      })
      .join('\n');
    next = next.slice(0, ms.index) + heading + filteredBody + next.slice(ms.index + ms[0].length);
  }

  // 3. Touch the Mermaid timeline: rename absorbed lane nodes to '<name><br/>released v<version>'.
  // Architect MEDIUM-2: widen the label-suffix match to accept hyphen / en-dash /
  // em-dash variants and any surrounding whitespace so consumers whose HISTORY-MAP
  // uses 'done - unreleased' or 'done – unreleased' still get the rename. The
  // node id is captured for re-emission so the replacement preserves whatever
  // identifier the source diagram used.
  for (const lane of lanes) {
    const nodeRe = new RegExp(
      `(\\b[A-Z][A-Z0-9_]*\\b)\\[${escapeRegex(lane.name)}<br/>done\\s*[-\\u2013\\u2014]\\s*unreleased\\]`,
      'g',
    );
    next = next.replace(nodeRe, (match, nodeId) => `${nodeId}[${lane.name}<br/>released v${version}]`);
  }

  return next;
}

// Trims the Open Decisions rows that describe release-composed lanes; leaves
// a single pointer at the new version entry in HISTORY-MAP. Conservative:
// if the kit's CURRENT-PLAN doesn't have absorbable detail, returns text
// unchanged. The CURRENT-PLAN edit during a routine release is dominated by
// the Mermaid status graph collapsing absorbed lane nodes into a single
// vX.Y.Z<br/>released node; that part is left to a follow-up D2.1 to avoid
// over-mutating in the first cut.
export function updateCurrentPlan(text, { version, lanes }) {
  // Append a release pointer at the bottom of the file (or just before the
  // last heading) so the next session can see the new version was composed.
  // The pointer is intentionally a comment because release composition is
  // expected to be followed by a curated CURRENT-PLAN refresh.
  if (lanes.length === 0) return text;
  const marker = `\n<!-- release composition pointer: v${version} composed lanes [${lanes.map((l) => l.name).join(', ')}] on ${todayIso()} — refresh this file's Active Lane and Open Decisions to remove release-composed detail. See HISTORY-MAP.md for the durable record. -->\n`;
  if (text.endsWith('\n')) return text + marker;
  return text + '\n' + marker;
}

export function updatePackageJson(text, version) {
  const json = JSON.parse(text);
  if (typeof json.version !== 'string') {
    throw new ReleaseComposeError('package.json: missing "version" field', { code: 'missing-version' });
  }
  json.version = version;
  return `${JSON.stringify(json, null, 2)}\n`;
}

// Keep a Changelog migration: rename the `## [Unreleased]` heading to
// `## [X.Y.Z] - YYYY-MM-DD` (preserving the body that followed it) and insert
// a fresh empty `## [Unreleased]` placeholder above it with the standard
// Added/Changed/Fixed scaffolding. Done by hand for v0.1.0 / v0.1.1 / v0.1.2;
// automated here (T3).
//
// Idempotency guard: if there is no `## [Unreleased]` heading, this is a
// no-op (returns the text unchanged) — the caller surfaces a diagnostic. The
// heading match is case-sensitive ("Unreleased" per the Keep a Changelog
// spec) and the existing line-ending style (LF or CRLF) is preserved.
const UNRELEASED_HEADING_RE = /^##[ \t]+\[Unreleased\][ \t]*$/m;

export function updateChangelog(text, { version, date }) {
  if (!UNRELEASED_HEADING_RE.test(text)) return text;
  const eol = /\r\n/.test(text) ? '\r\n' : '\n';
  const block = [
    '## [Unreleased]',
    '',
    '### Added',
    '',
    '### Changed',
    '',
    '### Fixed',
    '',
    `## [${version}] - ${date}`,
  ].join(eol);
  // Function replacer avoids `$`-pattern interpretation in the replacement.
  return text.replace(UNRELEASED_HEADING_RE, () => block);
}

// End-to-end planner. Returns a plan object the CLI can either print
// (under --check) or apply (under --write).
export function planRelease({ historyMapText, currentPlanText, packageJsonText, changelogText = null, opts = {} }) {
  const pkg = JSON.parse(packageJsonText);
  const previousVersion = pkg.version;
  const nextVersion = computeNextVersion(previousVersion, opts);
  const { lanes, diagnostics } = discoverClosedLanes(historyMapText, { includeDiagnostics: true });
  const date = opts.date || todayIso();

  if (lanes.length === 0 && !opts.allowEmpty) {
    const diagSuffix = diagnostics.length > 0 ? ` Diagnostic: ${diagnostics.join(' | ')}` : '';
    throw new ReleaseComposeError(
      `release compose: no closed-but-unreleased lanes found in HISTORY-MAP.md "Unreleased Workflow Evidence". Close at least one lane before composing a release, or pass --allow-empty for a maintenance release.${diagSuffix}`,
      { code: 'no-lanes' },
    );
  }

  const newHistoryMap = updateHistoryMap(historyMapText, { version: nextVersion, lanes, date });
  const newCurrentPlan = updateCurrentPlan(currentPlanText, { version: nextVersion, lanes });
  const newPackageJson = updatePackageJson(packageJsonText, nextVersion);

  // CHANGELOG.md is optional: only threaded when the caller supplies its text
  // (consumers may not keep a Keep-a-Changelog file). When present but lacking
  // an `## [Unreleased]` heading, updateChangelog is a no-op and we surface a
  // diagnostic so the operator knows the migration was skipped.
  let newChangelog = null;
  const changelogPresent = typeof changelogText === 'string';
  if (changelogPresent) {
    newChangelog = updateChangelog(changelogText, { version: nextVersion, date });
    if (newChangelog === changelogText) {
      diagnostics.push(
        `CHANGELOG.md: no '## [Unreleased]' heading found; skipped the [Unreleased] → [${nextVersion}] migration (CHANGELOG left unchanged). Add an '## [Unreleased]' section if you want release compose to migrate it.`,
      );
    }
  }

  return {
    previousVersion,
    version: nextVersion,
    date,
    lanes,
    diagnostics,
    newHistoryMap,
    newCurrentPlan,
    newPackageJson,
    changelogPresent,
    newChangelog,
    changes: {
      historyMap: historyMapText !== newHistoryMap,
      currentPlan: currentPlanText !== newCurrentPlan,
      packageJson: packageJsonText !== newPackageJson,
      changelog: changelogPresent && changelogText !== newChangelog,
    },
  };
}

export function formatPlanSummary(plan) {
  const lines = [];
  lines.push(`release compose plan:`);
  lines.push(`  previous version: ${plan.previousVersion}`);
  lines.push(`  next version:     ${plan.version}`);
  lines.push(`  release date:     ${plan.date}`);
  lines.push(`  lanes absorbed:   ${plan.lanes.length}`);
  for (const lane of plan.lanes) {
    lines.push(`    - ${lane.name} (${lane.archivePath})`);
  }
  // When --version matches the current version (pre-release-to-release
  // promotion), package.json is unchanged but the HISTORY-MAP entry is
  // still composed. Surface this so the operator does not read 'unchanged'
  // as 'nothing happens'. Phase F architect MEDIUM-3.
  const pkgNote = plan.changes.packageJson
    ? 'WOULD UPDATE'
    : (plan.previousVersion === plan.version
      ? 'unchanged (--version matches current; pre-release-to-release promotion)'
      : 'unchanged');
  lines.push(`  files to mutate:`);
  lines.push(`    docs/HISTORY-MAP.md   ${plan.changes.historyMap ? 'WOULD UPDATE' : 'unchanged'}`);
  lines.push(`    docs/CURRENT-PLAN.md  ${plan.changes.currentPlan ? 'WOULD UPDATE' : 'unchanged'}`);
  lines.push(`    package.json          ${pkgNote}`);
  if (plan.changelogPresent) {
    lines.push(`    CHANGELOG.md          ${plan.changes.changelog ? 'WOULD MIGRATE' : 'unchanged (no [Unreleased] heading)'}`);
  }
  return lines.join('\n');
}

function escapeRegex(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
