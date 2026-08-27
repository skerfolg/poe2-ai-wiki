#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { listStagedFiles, evaluateStagedPlan } from './lib/staged-plan-rule.mjs';
import { attributeChoiceNodes, evaluateAssemblySpec } from './lib/assembly-gate-rule.mjs';

// Workflow Governance Kit — Claude PreToolUse hook handler.
//
// Reads the Claude Code PreToolUse JSON payload from stdin. Decides whether
// to allow, warn, or block the planned tool call based on workflow-governance
// rules. Block decisions exit with code 2 (Claude PreToolUse semantics).
//
// The actual rule (non-doc staged without docs/CURRENT-PLAN.md) lives in
// scripts/lib/staged-plan-rule.mjs and is shared with the universal
// scripts/workflow-precommit.mjs gate. This hook is the Claude-specific entry
// point; the universal gate fires for every agent and for plain terminal
// commits via .githooks/pre-commit.

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function readPayload() {
  const raw = readStdin();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function isGitCommitCommand(command) {
  if (!command || typeof command !== 'string') return false;
  return /\bgit\s+commit\b/.test(command);
}

function emitDeny(reason) {
  process.stderr.write(`[workflow-governance pretooluse] ${reason}\n`);
  process.exit(2);
}

function evaluateBash(toolInput) {
  const command = toolInput && toolInput.command;
  if (!isGitCommitCommand(command)) return;

  const result = evaluateStagedPlan(listStagedFiles());
  if (result.ok) return;

  emitDeny(result.message);
}

// #129 — 조립·계산 도구는 **필수 절차를 건너뛰면 거부**한다.
//
// ⚠ `compute_pob`도 포함한다. 안 그러면 조립을 피하고 계산 수치만 보고하는 경로로
// 샌다 — 2026-08-27 사고가 정확히 그 경로였다(수치 먼저 보고, 조립은 마지막).
const ASSEMBLY_TOOLS = /(^|__)(assemble_pob|compute_pob)$/;

function evaluateAssembly(toolInput) {
  const spec = toolInput && toolInput.build_spec;
  if (!spec) return;
  const result = evaluateAssemblySpec(spec, attributeChoiceNodes());
  if (result.ok) return;
  emitDeny(result.message);
}

const payload = readPayload();
const toolName = payload && payload.tool_name;
const toolInput = (payload && payload.tool_input) || {};

if (toolName === 'Bash') {
  evaluateBash(toolInput);
} else if (typeof toolName === 'string' && ASSEMBLY_TOOLS.test(toolName)) {
  evaluateAssembly(toolInput);
}

// Default decision: allow.
process.exit(0);
