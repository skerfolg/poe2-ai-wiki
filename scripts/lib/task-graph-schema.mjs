// Workflow Governance Kit — task graph schema and validators.
//
// This module is the single source of truth for the on-disk shape of
// `tasks/state.json` and the rules that govern it. The CLI in
// `bin/workflow-governance.mjs` (or its sibling) consumes this module;
// every read or write of the state file MUST go through `readState` /
// `writeState` so that schema invariants and the DAG constraint stay
// enforced regardless of which CLI verb runs.
//
// The contract that this module implements is documented in
// `docs/TASK-GRAPH.md`. If the two ever disagree, the policy doc wins
// and this module must be brought back into compliance.

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export const STATE_VERSION = 1;
export const TASK_STATUSES = Object.freeze(['open', 'in-progress', 'blocked', 'done']);
export const TASK_ID_REGEX = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const TITLE_MAX = 120;
export const NOTES_MAX = 1024;

const ALLOWED_TRANSITIONS = Object.freeze({
  open: new Set(['in-progress', 'blocked']),
  'in-progress': new Set(['blocked', 'done']),
  blocked: new Set(['open', 'in-progress']),
  done: new Set(['open']), // requires --reopen at the CLI layer
});

export class SchemaError extends Error {
  constructor(message, { code = 'schema-error' } = {}) {
    super(message);
    this.name = 'SchemaError';
    this.code = code;
  }
}

export function emptyState() {
  return { version: STATE_VERSION, tasks: {} };
}

export function validateTask(task, { context = 'task' } = {}) {
  if (!task || typeof task !== 'object') {
    throw new SchemaError(`${context} must be an object`);
  }
  if (typeof task.id !== 'string' || !TASK_ID_REGEX.test(task.id)) {
    throw new SchemaError(`${context}.id must match ${TASK_ID_REGEX} (got: ${JSON.stringify(task.id)})`, { code: 'invalid-id' });
  }
  if (typeof task.title !== 'string' || task.title.length === 0 || task.title.length > TITLE_MAX) {
    throw new SchemaError(`${context}.title must be a non-empty string up to ${TITLE_MAX} chars`, { code: 'invalid-title' });
  }
  if (typeof task.lane !== 'string' || task.lane.length === 0) {
    throw new SchemaError(`${context}.lane must be a non-empty string`, { code: 'invalid-lane' });
  }
  if (!TASK_STATUSES.includes(task.status)) {
    throw new SchemaError(`${context}.status must be one of ${TASK_STATUSES.join(', ')} (got: ${JSON.stringify(task.status)})`, { code: 'invalid-status' });
  }
  if (!Array.isArray(task.dependsOn) || !task.dependsOn.every((d) => typeof d === 'string' && TASK_ID_REGEX.test(d))) {
    throw new SchemaError(`${context}.dependsOn must be an array of valid task ids`, { code: 'invalid-depends-on' });
  }
  if (new Set(task.dependsOn).size !== task.dependsOn.length) {
    throw new SchemaError(`${context}.dependsOn contains duplicate ids`, { code: 'duplicate-edge' });
  }
  if (task.dependsOn.includes(task.id)) {
    throw new SchemaError(`${context}.dependsOn must not contain the task's own id (self-loop)`, { code: 'self-loop' });
  }
  if (typeof task.createdAt !== 'string' || Number.isNaN(Date.parse(task.createdAt))) {
    throw new SchemaError(`${context}.createdAt must be an ISO-8601 timestamp string`, { code: 'invalid-timestamp' });
  }
  if (typeof task.updatedAt !== 'string' || Number.isNaN(Date.parse(task.updatedAt))) {
    throw new SchemaError(`${context}.updatedAt must be an ISO-8601 timestamp string`, { code: 'invalid-timestamp' });
  }
  if (task.closedAt !== undefined && task.closedAt !== null) {
    if (typeof task.closedAt !== 'string' || Number.isNaN(Date.parse(task.closedAt))) {
      throw new SchemaError(`${context}.closedAt must be an ISO-8601 timestamp string or omitted`, { code: 'invalid-timestamp' });
    }
  }
  if (task.status === 'done' && !task.closedAt) {
    throw new SchemaError(`${context}.closedAt is required when status is 'done'`, { code: 'missing-closed-at' });
  }
  if (task.status !== 'done' && task.closedAt) {
    throw new SchemaError(`${context}.closedAt must be cleared when status is not 'done'`, { code: 'stale-closed-at' });
  }
  if (task.notes !== undefined && task.notes !== null) {
    if (typeof task.notes !== 'string' || task.notes.length > NOTES_MAX) {
      throw new SchemaError(`${context}.notes must be a string up to ${NOTES_MAX} chars`, { code: 'invalid-notes' });
    }
  }
}

export function validateState(state) {
  if (!state || typeof state !== 'object') {
    throw new SchemaError('state must be an object');
  }
  if (state.version !== STATE_VERSION) {
    throw new SchemaError(
      `unknown state.version: ${JSON.stringify(state.version)} (expected ${STATE_VERSION}). Refusing to operate on an unrecognised schema; upgrade the CLI or run a migration.`,
      { code: 'unknown-version' },
    );
  }
  if (!state.tasks || typeof state.tasks !== 'object' || Array.isArray(state.tasks)) {
    throw new SchemaError('state.tasks must be a plain object keyed by task id', { code: 'invalid-tasks-shape' });
  }
  for (const [id, task] of Object.entries(state.tasks)) {
    if (id !== task.id) {
      throw new SchemaError(`state.tasks key '${id}' does not match task.id '${task.id}'`, { code: 'id-mismatch' });
    }
    validateTask(task, { context: `state.tasks[${id}]` });
  }
  // Edges must point to existing tasks.
  for (const task of Object.values(state.tasks)) {
    for (const dep of task.dependsOn) {
      if (!Object.prototype.hasOwnProperty.call(state.tasks, dep)) {
        throw new SchemaError(`task '${task.id}' depends on missing task '${dep}'`, { code: 'missing-target' });
      }
    }
  }
  // DAG invariant: no cycles.
  detectCycle(state);
  // Dependency-status invariant (docs/TASK-GRAPH.md §3): a task that has
  // moved past `open` (status in {in-progress, done}) must have ALL of its
  // dependencies in `done`. `open` and `blocked` are exempt — they have not
  // yet committed to executing. This catches:
  //   - `open -> in-progress` with an open/blocked dependency
  //   - reopening a `done` task whose downstream consumers are already
  //     in-progress / done (a cascading-reopen footgun)
  for (const task of Object.values(state.tasks)) {
    if (task.status !== 'in-progress' && task.status !== 'done') continue;
    const blocking = task.dependsOn.filter((dep) => state.tasks[dep].status !== 'done');
    if (blocking.length > 0) {
      throw new SchemaError(
        `task '${task.id}' is '${task.status}' but has non-done dependency(ies): ${blocking.join(', ')} (see docs/TASK-GRAPH.md §3)`,
        { code: 'dependency-not-done' },
      );
    }
  }
}

export function getBlockingDependencies(state, taskId) {
  const task = state.tasks[taskId];
  if (!task) return [];
  return task.dependsOn.filter((dep) => state.tasks[dep] && state.tasks[dep].status !== 'done');
}

export function detectCycle(state) {
  // Kahn's algorithm. Throws SchemaError on cycle; returns silently on success.
  const ids = Object.keys(state.tasks);
  const inDegree = Object.create(null);
  for (const id of ids) inDegree[id] = state.tasks[id].dependsOn.length;

  const queue = ids.filter((id) => inDegree[id] === 0);
  // Index dependents for O(V+E) traversal.
  const dependents = Object.create(null);
  for (const id of ids) dependents[id] = [];
  for (const task of Object.values(state.tasks)) {
    for (const dep of task.dependsOn) {
      if (dependents[dep]) dependents[dep].push(task.id);
    }
  }

  let visited = 0;
  while (queue.length) {
    const id = queue.shift();
    visited += 1;
    for (const child of dependents[id] || []) {
      inDegree[child] -= 1;
      if (inDegree[child] === 0) queue.push(child);
    }
  }
  if (visited < ids.length) {
    const stuck = ids.filter((id) => inDegree[id] > 0);
    throw new SchemaError(
      `task graph contains a cycle (tasks unreachable in topological order: ${stuck.join(', ')})`,
      { code: 'cycle' },
    );
  }
}

export function canTransition(from, to) {
  return ALLOWED_TRANSITIONS[from] && ALLOWED_TRANSITIONS[from].has(to);
}

export function readState(filePath) {
  if (!existsSync(filePath)) {
    return emptyState();
  }
  let raw;
  try {
    raw = readFileSync(filePath, 'utf8');
  } catch (err) {
    throw new SchemaError(`failed to read ${filePath}: ${err.message}`, { code: 'io-read' });
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new SchemaError(`failed to parse ${filePath}: ${err.message}`, { code: 'parse-error' });
  }
  validateState(parsed);
  return parsed;
}

export function writeState(filePath, state) {
  validateState(state);
  const dir = dirname(filePath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  // Atomic write: stage to .tmp then rename. Avoids leaving a half-written
  // state.json if the process is interrupted between the open and close.
  const tmpPath = `${filePath}.tmp`;
  const json = `${JSON.stringify(state, null, 2)}\n`;
  writeFileSync(tmpPath, json, 'utf8');
  renameSync(tmpPath, filePath);
}

export function nowIsoTimestamp() {
  return new Date().toISOString();
}
