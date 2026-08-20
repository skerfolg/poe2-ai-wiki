#!/usr/bin/env node
// Workflow Governance Kit — universal git pre-commit gate.
//
// Runs from .githooks/pre-commit on every `git commit`, regardless of which
// agent (Claude, Codex, Cursor, Aider, Cline) or human ran the command.
// Enforces the same "non-doc staged without docs/CURRENT-PLAN.md" rule as the
// Claude PreToolUse hook (scripts/workflow-pretooluse.mjs), giving every coding
// agent — and every plain `git commit` from a terminal — the same fail-closed
// behavior.
//
// Exit codes:
//   0  rule satisfied (or nothing staged)
//   1  rule violated; the commit is aborted
//
// To bypass intentionally (rare and visible), use `git commit --no-verify`.

import { listStagedFiles, evaluateStagedPlan } from './lib/staged-plan-rule.mjs';

const result = evaluateStagedPlan(listStagedFiles());
if (result.ok) {
  process.exit(0);
}

process.stderr.write(`[workflow-governance pre-commit] ${result.message}\n`);
process.exit(1);
