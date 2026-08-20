#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const planPath = path.join(root, 'docs', 'CURRENT-PLAN.md');
const guardPath = path.join(root, 'scripts', 'workflow-guard.mjs');

function read(file) {
  try {
    return readFileSync(file, 'utf8');
  } catch {
    return '';
  }
}

function firstMatch(text, regex) {
  const match = regex.exec(text);
  return match ? match[1].trim() : '';
}

function extractActiveLane(plan) {
  const explicit = firstMatch(plan, /^Lane:\s*(.+)$/m) || firstMatch(plan, /^Version\/lane:\s*(.+)$/m);
  if (explicit) return explicit;
  const headerLine = firstMatch(plan, /^Active lane:\s*(.+)$/m);
  return headerLine || '(active lane not parsed; read docs/CURRENT-PLAN.md directly)';
}

function extractIntegrationBranch(plan) {
  const explicit = firstMatch(plan, /^\*\*Integration branch\*\*:\s*(.+)$/m);
  if (explicit) return explicit;
  const inline = firstMatch(plan, /^Integration branch:\s*(.+)$/m);
  if (inline) return inline;
  return '(integration branch not declared; default per kit convention is `main`)';
}

function gitOneliner(args) {
  try {
    return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch {
    return '';
  }
}

function runGuardSummary() {
  if (!existsSync(guardPath)) return '(guard script not installed)';
  try {
    const raw = execFileSync(process.execPath, [guardPath, 'status'], {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const lines = raw.split(/\r?\n/);
    const summary = lines.find((line) => line.startsWith('summary:')) || '(no guard summary line)';
    const warnings = lines.filter((line) => line.startsWith('warning:'));
    const errors = lines.filter((line) => line.startsWith('error:'));
    const parts = [summary];
    if (warnings.length > 0) parts.push(...warnings);
    if (errors.length > 0) parts.push(...errors);
    return parts.join('\n');
  } catch (err) {
    return `(guard execution failed: ${err.message})`;
  }
}

function emit(line) {
  process.stdout.write(`${line}\n`);
}

const plan = read(planPath);

emit('==== Workflow Governance Briefing ====');
emit('');
if (!plan) {
  emit('docs/CURRENT-PLAN.md is missing. Invoke the workflow-init skill or run `npx @workflow-governance/kit init --write` before any code change.');
} else {
  emit(`Active lane: ${extractActiveLane(plan)}`);
  emit(`Integration branch: ${extractIntegrationBranch(plan)}`);
  const branch = gitOneliner(['rev-parse', '--abbrev-ref', 'HEAD']);
  if (branch) emit(`Current branch: ${branch}`);
  const head = gitOneliner(['log', '-1', '--pretty=%h %s']);
  if (head) emit(`Latest commit: ${head}`);
  emit('');
  emit('Pre-flight reminders:');
  emit('  1. Read docs/CURRENT-PLAN.md before any code change.');
  emit('  2. Update CURRENT-PLAN.md (text + Mermaid) in lockstep with status-affecting work.');
  emit('  3. Invoke `workflow-status` before implementation/closure work; `workflow-close` at closure; `workflow-release` at release composition.');
  emit('  4. Branch only from the integration branch above; non-default bases require an Integration Branch Override entry in CURRENT-PLAN.md.');
  emit('  5. Never treat per-agent runtime notes (.omc/, .omx/, .codex/local/, .claude/local/) as active control.');
}
emit('');
emit('Guard status:');
emit(runGuardSummary());
