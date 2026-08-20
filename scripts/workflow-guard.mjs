#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { readState } from './lib/task-graph-schema.mjs';
import {
  TASK_RENDER_REL,
  TASK_STATE_REL,
  checkTaskGraphInSync,
} from './lib/task-graph-render.mjs';
import { CONFIG_FILENAME, ConfigError, readConfig } from './lib/config-schema.mjs';
import { PLAN_STATES, validateCurrentPlan, validateHistoryMap } from './lib/live-doc-schema.mjs';

const mode = process.argv[2] || 'status';
const root = process.cwd();

const requiredDocs = [
  'docs/WORKFLOW-GOVERNANCE.md',
  'docs/CURRENT-PLAN.md',
  'docs/HISTORY-MAP.md',
  'AGENTS.md',
  'CLAUDE.md',
];

const statusTokens = [
  'PASS',
  'PARTIAL',
  'FAIL',
  'NOT STARTED',
  'done',
  'active',
  'blocked',
  'deferred',
  'superseded',
  'candidate',
];

const result = { errors: [], warnings: [], info: [] };

function rel(file) {
  return file.replaceAll('\\', '/');
}

function exists(file) {
  return existsSync(path.join(root, file));
}

function read(file) {
  return readFileSync(path.join(root, file), 'utf8');
}

function runGit(args) {
  try {
    return execFileSync('git', args, {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
  } catch {
    return '';
  }
}

function extractMermaidBlocks(markdown) {
  const blocks = [];
  const regex = /```mermaid\s*([\s\S]*?)```/g;
  let match;
  while ((match = regex.exec(markdown)) !== null) blocks.push(match[1]);
  return blocks;
}

function addStatusTokens(target, text) {
  for (const token of statusTokens) {
    if (text.includes(token)) target.add(token);
  }
}

function extractTextStatuses(markdown) {
  const statuses = new Set();
  const inlineStatus = /Status:\s*`([^`]+)`/gi;
  let match;
  while ((match = inlineStatus.exec(markdown)) !== null) addStatusTokens(statuses, match[1]);
  for (const token of statusTokens) {
    if (markdown.includes(`\`${token}\``)) statuses.add(token);
  }
  return statuses;
}

function extractGraphStatuses(blocks) {
  const statuses = new Set();
  for (const block of blocks) addStatusTokens(statuses, block);
  return statuses;
}

function extractFirstBacktickToken(text, prefixPattern) {
  const re = new RegExp(`^(?:${prefixPattern}):.*?\`([^\`]+)\``, 'm');
  const match = re.exec(text);
  return match ? match[1].trim() : null;
}

// DIVERGENCE (Phase 3): this legacy parser accepts Version/lane: form,
// while scripts/lib/live-doc-schema.mjs detectState() rejects it per §12.1
// deprecation. The two parsers coexist intentionally during the v0.1.x
// transition; Phase 4 migrate-docs CLI reconciles consumer documents.
function extractActiveLane(planContent) {
  return (
    extractFirstBacktickToken(planContent, 'Lane') ||
    extractFirstBacktickToken(planContent, 'Active lane') ||
    extractFirstBacktickToken(planContent, 'Version\\/lane')
  );
}

function extractIntegrationBranch(planContent) {
  const bold = /\*\*Integration branch\*\*:\s*`([^`]+)`/m.exec(planContent);
  if (bold) return bold[1].trim();
  const inline = /^Integration branch:\s*`([^`]+)`/m.exec(planContent);
  if (inline) return inline[1].trim();
  return null;
}

function stripFencedCodeBlocks(text) {
  return text.replace(/```[\s\S]*?```/g, '');
}

function hasIntegrationBranchOverride(planContent) {
  // Genuine override prose names the override branch and its default. The
  // template ships a placeholder section that only describes the override
  // pattern inside a code block; stripping fenced blocks before matching
  // avoids treating that example text as an active override.
  const stripped = stripFencedCodeBlocks(planContent);
  return /This lane targets\s*`[^`]+`\s*instead of/i.test(stripped);
}

function checkRequiredDocs() {
  for (const file of requiredDocs) {
    if (!exists(file)) result.errors.push(`missing required workflow document: ${file}`);
  }
}

function checkThinEntrypoints() {
  const policyHeadingRegex = /^#+\s+(Baseline Phase Control|Version Closure)\b/m;
  for (const file of ['AGENTS.md', 'CLAUDE.md']) {
    if (!exists(file)) continue;
    const content = read(file);
    if (!content.includes('docs/WORKFLOW-GOVERNANCE.md')) {
      result.warnings.push(`${file} does not reference docs/WORKFLOW-GOVERNANCE.md`);
    }
    if (policyHeadingRegex.test(content)) {
      result.warnings.push(
        `${file} contains a Markdown heading that mirrors a workflow policy section title (Baseline Phase Control / Version Closure); embed a citation, not a copy.`,
      );
    }
  }
}

function checkMermaid(file, required) {
  if (!exists(file)) return;
  const content = read(file);
  const blocks = extractMermaidBlocks(content);
  if (required && blocks.length === 0) {
    result.errors.push(`${file} has no Mermaid status view`);
    return;
  }
  if (blocks.length === 0) {
    result.warnings.push(`${file} has no Mermaid status view`);
    return;
  }
  const textStatuses = extractTextStatuses(content);
  const graphStatuses = extractGraphStatuses(blocks);
  const missingFromGraph = [...textStatuses].filter((token) => !graphStatuses.has(token));
  if (missingFromGraph.length > 0) {
    result.warnings.push(`${file} status tokens appear in text but not Mermaid: ${missingFromGraph.join(', ')}`);
  }
  result.info.push(`${file}: ${blocks.length} Mermaid block(s), ${graphStatuses.size} graph status token(s)`);
}

function checkGitHygiene() {
  const currentPlan = exists('docs/CURRENT-PLAN.md') ? read('docs/CURRENT-PLAN.md') : '';
  const porcelain = runGit(['status', '--porcelain', '-uall']);
  if (porcelain) {
    const lines = porcelain.split(/\r?\n/).filter(Boolean);
    result.info.push(`git working tree has ${lines.length} changed path(s)`);
    const codeChanges = lines.filter((line) => {
      const file = line.slice(3);
      return file.startsWith('src/') || file.startsWith('resources/') || file.startsWith('scripts/') || file === 'package.json';
    });
    const planTouched = lines.some((line) => line.includes('docs/CURRENT-PLAN.md'));
    if (codeChanges.length > 0 && !planTouched) {
      result.warnings.push('code/tooling changes detected without docs/CURRENT-PLAN.md in git status');
    }
  } else {
    result.info.push('git working tree has no changed paths');
  }

  const worktrees = runGit(['worktree', 'list', '--porcelain']);
  const worktreePaths = worktrees
    .split(/\r?\n/)
    .filter((line) => line.startsWith('worktree '))
    .map((line) => line.slice('worktree '.length));
  const extraWorktrees = worktreePaths.filter((item) => path.resolve(item) !== root);
  const untrackedWorktrees = extraWorktrees.filter((item) => {
    const normalized = rel(item);
    const marker = `.worktrees/${path.basename(item)}`;
    return !currentPlan.includes(normalized) && !currentPlan.includes(marker);
  });
  if (untrackedWorktrees.length > 0) {
    result.warnings.push(`extra worktree(s) not named in Current Plan: ${untrackedWorktrees.join('; ')}`);
  }

  const branches = runGit(['branch', '--format=%(refname:short)']);
  const tempBranches = branches.split(/\r?\n/).filter((branch) => /^(feat|spike|tmp|wip)\//.test(branch));
  const untrackedBranches = tempBranches.filter((branch) => !currentPlan.includes(branch));
  if (untrackedBranches.length > 0) {
    result.warnings.push(`temporary branch candidate(s) not named in Current Plan: ${untrackedBranches.join(', ')}`);
  }
}

function checkLaneBranchCoherence() {
  if (!exists('docs/CURRENT-PLAN.md')) return;
  const content = read('docs/CURRENT-PLAN.md');
  const lane = extractActiveLane(content);
  const integration = extractIntegrationBranch(content);
  const overridePresent = hasIntegrationBranchOverride(content);
  const currentBranch = runGit(['rev-parse', '--abbrev-ref', 'HEAD']);
  if (!currentBranch) return;

  if (integration && currentBranch === integration) return;
  if (lane && currentBranch.includes(lane)) return;
  if (/^(feat|feature|spike|tmp|wip)\//.test(currentBranch) && content.includes(currentBranch)) return;

  const expectedLabel = integration ? `'${integration}'` : '(integration branch not declared in CURRENT-PLAN.md)';
  const laneLabel = lane ? `'${lane}'` : '(active lane not parsed)';
  const overrideHint = overridePresent
    ? ' An Integration Branch Override section is present; verify this branch matches the override target.'
    : ' If intentional, record an Integration Branch Override entry in CURRENT-PLAN.md.';
  result.warnings.push(
    `current branch '${currentBranch}' does not match the integration branch ${expectedLabel} or contain the active lane name ${laneLabel}.${overrideHint}`,
  );
}

function checkComposedMilestones() {
  if (!exists('docs/HISTORY-MAP.md')) return;
  const content = read('docs/HISTORY-MAP.md');
  // Accept both LF and CRLF line endings: a Windows checkout without
  // text=auto eol=lf normalisation in .gitattributes would otherwise miss
  // every section boundary, silently disabling this gate. Phase F architect
  // review caught this as the one remaining bare-\n split among the 11+
  // split call sites in the codebase.
  const sections = content.split(/\r?\n(?=### )/);
  for (const section of sections) {
    const headerLine = section.split(/\r?\n/)[0];
    if (!/^### /.test(headerLine)) continue;
    if (!/v\d+\.\d+\.\d+/i.test(headerLine)) continue;
    const statusMatch = /^Status:\s*`?([^`\n]+)`?/m.exec(section);
    if (!statusMatch) continue;
    const status = statusMatch[1].trim();
    if (!/(released|done|development-closed|release-blocked)/i.test(status)) continue;
    if (!/Composed milestones:/i.test(section)) {
      const heading = headerLine.replace(/^### /, '');
      result.warnings.push(
        `HISTORY-MAP.md version entry "${heading}" has status "${status}" but no "Composed milestones:" line; per WORKFLOW-GOVERNANCE.md §3 every released version entry must list its absorbed lanes.`,
      );
    }
  }
}

function checkCleanupCandidates() {
  for (const candidate of ['.tmp-tests', 'dist', 'out', 'playwright-report', 'test-results']) {
    if (exists(candidate)) result.warnings.push(`cleanup candidate exists: ${candidate}`);
  }
  for (const entry of safeReadDir(root)) {
    if (/^tmp[-_.]/i.test(entry) || /^debug[-_.]/i.test(entry) || /\.tmp$/i.test(entry)) {
      result.warnings.push(`root temporary-name candidate exists: ${entry}`);
    }
  }
}

function safeReadDir(dir) {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

function checkTaskGraphRender() {
  // Optional: only enforce when the consumer is using the task graph.
  // The schema/render libs live alongside this script, but the data file
  // (tasks/state.json) only exists once a consumer has called `task add`.
  const statePath = path.join(root, TASK_STATE_REL);
  if (!existsSync(statePath)) {
    result.info.push(`tasks/state.json not present; task graph check skipped`);
    return;
  }
  let state;
  try {
    state = readState(statePath);
  } catch (err) {
    result.errors.push(`${TASK_STATE_REL}: ${err.message}`);
    return;
  }
  const renderPath = path.join(root, TASK_RENDER_REL);
  try {
    checkTaskGraphInSync(renderPath, state);
    const taskCount = Object.keys(state.tasks).length;
    result.info.push(`${TASK_STATE_REL}: ${taskCount} task(s) in sync with ${TASK_RENDER_REL}`);
  } catch (err) {
    result.errors.push(`task graph: ${err.message}`);
  }
}

function checkConfigPresence() {
  // E4 signposting. Absent config is informational (the v0.1.0 fallback path
  // keeps Node consumers working without setup); invalid config is an error
  // (the precommit gate must block before bad config reaches the CLI's
  // dispatch).
  const cfgPath = path.join(root, CONFIG_FILENAME);
  if (!existsSync(cfgPath)) {
    result.info.push(`${CONFIG_FILENAME} not present; kit falls back to v0.1.0 npm-flavoured defaults. Run /workflow-setup in your coding agent to configure for non-Node stacks.`);
    return;
  }
  try {
    const cfg = readConfig(cfgPath);
    if (cfg) {
      result.info.push(`${CONFIG_FILENAME}: stack=${cfg.stack.primary}, ${Object.keys(cfg.commands).length} command slot(s) set, ci.provider=${cfg.ci.provider}`);
    }
  } catch (err) {
    if (err instanceof ConfigError) {
      result.errors.push(`${CONFIG_FILENAME}: ${err.message} [${err.code}]`);
    } else {
      result.errors.push(`${CONFIG_FILENAME}: ${err.message}`);
    }
  }
}

function routeLiveDocDiagnostics(libResult, prefix) {
  for (const d of libResult.errors) result.errors.push(`${prefix}${d.message}`);
  for (const d of libResult.warnings) result.warnings.push(`${prefix}${d.message}`);
  for (const d of libResult.info) result.info.push(`${prefix}${d.message}`);
}

function checkLiveDocSchema() {
  // CURRENT-PLAN.md branch
  if (exists('docs/CURRENT-PLAN.md')) {
    const cpResult = validateCurrentPlan(read('docs/CURRENT-PLAN.md'));
    if (cpResult.state === PLAN_STATES.MALFORMED) {
      // §13 backward-compat (Phase 3 plan Decision 2 / REQ 1): library emits
      // ERROR for malformed state but the guard demotes to WARNING so v0.1.x
      // consumers using deprecated `Version/lane:` do not have their
      // precommit gate break on upgrade. The disclosure text below makes
      // the enforcement gap visible. Phase 4 migrate-docs CLI provides the
      // migration path and may later escalate to ERROR.
      result.warnings.push(
        'live-doc-schema(CURRENT-PLAN.md): CURRENT-PLAN.md state is malformed (no Lane:/Active lane: field, or only deprecated Version/lane: form). Section ordering, header fields, and §13 Canonical Next Step checks were SKIPPED for this document. Migrate to Lane: per §12.1. Run workflow-governance migrate-docs --check (v0.1.3+) for automated detection.',
      );
    } else {
      routeLiveDocDiagnostics(cpResult, 'live-doc-schema(CURRENT-PLAN.md): ');
    }
  }

  // HISTORY-MAP.md branch (no malformed state concept)
  if (exists('docs/HISTORY-MAP.md')) {
    const hmResult = validateHistoryMap(read('docs/HISTORY-MAP.md'));
    routeLiveDocDiagnostics(hmResult, 'live-doc-schema(HISTORY-MAP.md): ');
  }
}

function checkMirrorFiles() {
  // templates/docs/CURRENT-PLAN.md and templates/docs/HISTORY-MAP.md are
  // scaffolds (placeholder content), not mirrors of the kit's live docs —
  // only WORKFLOW-GOVERNANCE.md is a true policy mirror.
  const a = 'docs/WORKFLOW-GOVERNANCE.md';
  const b = 'templates/docs/WORKFLOW-GOVERNANCE.md';

  if (!exists(a) || !exists(b)) {
    result.info.push(`mirror check skipped: ${exists(a) ? b : a} not present`);
    return;
  }

  // Strip UTF-8 BOM (U+FEFF) before comparison. The guard's `read()` does
  // not strip BOM (unlike the library's `normalizeInput()`), so a Windows
  // editor BOM injection on one copy would spuriously fail mirror check.
  // Inlining the one-char replace is preferred over importing
  // `__internals.normalizeInput` because `__internals` is declared as
  // test-only API.
  const aContent = read(a).replace(/^﻿/, '');
  const bContent = read(b).replace(/^﻿/, '');

  if (aContent === bContent) {
    result.info.push(`${a} and ${b} are byte-identical (mirror check PASS)`);
  } else {
    result.errors.push(
      `${a} and ${b} have diverged; they must be byte-identical. Copy the authoritative source to the other after edits.`,
    );
  }
}

function printReport() {
  console.log(`Workflow guard mode: ${mode}`);
  console.log('');
  for (const item of result.info) console.log(`info: ${item}`);
  for (const item of result.warnings) console.warn(`warning: ${item}`);
  for (const item of result.errors) console.error(`error: ${item}`);
  console.log('');
  console.log(`summary: ${result.errors.length} error(s), ${result.warnings.length} warning(s), ${result.info.length} info item(s)`);
}

checkRequiredDocs();
checkThinEntrypoints();

if (mode === 'status' || mode === 'mermaid' || mode === 'precommit') {
  checkMermaid('docs/CURRENT-PLAN.md', true);
  checkMermaid('docs/HISTORY-MAP.md', false);
  checkComposedMilestones();
  checkTaskGraphRender();
  checkConfigPresence();
  checkLiveDocSchema();
  // §13 Canonical Next Step diagnostics are routed through checkLiveDocSchema()
  // because the library's validateCurrentPlan() invokes the §13 sub-routine
  // internally — see Phase 3 plan Decision 1 (M1: Merged).
  checkMirrorFiles();
}

if (mode === 'status' || mode === 'cleanup' || mode === 'precommit') {
  checkGitHygiene();
  checkCleanupCandidates();
  checkLaneBranchCoherence();
}

if (!['status', 'mermaid', 'cleanup', 'precommit'].includes(mode)) {
  result.errors.push(`unknown mode: ${mode}`);
}

printReport();

// Use process.exitCode (not process.exit) so any beforeExit handlers run.
// The script is at the end of its synchronous flow here; execution will fall
// off naturally with the requested exit code.
if (result.errors.length > 0) process.exitCode = 1;
