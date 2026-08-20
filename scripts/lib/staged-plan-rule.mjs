// Workflow Governance Kit — shared "non-doc staged without CURRENT-PLAN" rule.
//
// This module is shared by:
//   - scripts/workflow-precommit.mjs   (universal git pre-commit gate)
//   - scripts/workflow-pretooluse.mjs  (Claude PreToolUse hook)
//
// Both gates enforce the same rule from WORKFLOW-GOVERNANCE.md §2:
// every commit that touches code or tooling outside docs/ must also stage
// docs/CURRENT-PLAN.md in the same commit. The two gates differ only in their
// trigger and their exit-code convention; the evaluation is identical.

import { execFileSync } from 'node:child_process';

export const PLAN_PATH = 'docs/CURRENT-PLAN.md';
export const DOC_PREFIX = 'docs/';

export function listStagedFiles({ cwd = process.cwd() } = {}) {
  try {
    const out = execFileSync('git', ['diff', '--cached', '--name-only'], {
      cwd,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return out
      .trim()
      .split(/\r?\n/)
      .filter(Boolean);
  } catch {
    return [];
  }
}

export function classifyStaged(files) {
  const planTouched = files.includes(PLAN_PATH);
  const nonDocChanges = files.filter((file) => !file.startsWith(DOC_PREFIX));
  return { planTouched, nonDocChanges };
}

export function evaluateStagedPlan(files) {
  if (!Array.isArray(files) || files.length === 0) {
    return { ok: true, reason: 'no-staged-files' };
  }
  const { planTouched, nonDocChanges } = classifyStaged(files);
  // Order matters: check `doc-only` before `plan-staged` so that a docs-only
  // commit (which may or may not include the plan file) reports the more
  // specific reason `doc-only`. The previous ordering let `plan-staged`
  // shadow `doc-only` whenever the plan happened to be staged, which made
  // any future caller branching on `reason` produce the wrong message.
  if (nonDocChanges.length === 0) return { ok: true, reason: 'doc-only' };
  if (planTouched) return { ok: true, reason: 'plan-staged' };
  return {
    ok: false,
    reason: 'non-doc-without-plan',
    nonDocChanges,
    message: buildBlockMessage(nonDocChanges),
  };
}

export function buildBlockMessage(nonDocChanges) {
  const sample = nonDocChanges.slice(0, 5).join(', ');
  const overflow = nonDocChanges.length > 5 ? `, +${nonDocChanges.length - 5} more` : '';
  return (
    `Blocked: this commit stages non-doc changes (${sample}${overflow}) without ` +
    `staging ${PLAN_PATH}. Per WORKFLOW-GOVERNANCE.md §2 (Current Plan Freshness), ` +
    `every status-affecting change must update ${PLAN_PATH} (text + Mermaid status ` +
    `graph) in the same commit. Stage ${PLAN_PATH} or amend the change set, then retry.`
  );
}
