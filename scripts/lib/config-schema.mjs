// Workflow Governance Kit — .workflow-governance.json schema and validators.
//
// This module is the single source of truth for the on-disk shape of
// .workflow-governance.json and the rules that govern it. Every kit
// integration point — pre-commit gate, release publish, install-ci's CI
// template, and the workflow-setup skill — MUST read/write the config
// only via this module so that schema invariants stay enforced.
//
// The contract this module implements is documented in
// docs/WORKFLOW-GOVERNANCE.md §11. If the two ever disagree, the policy
// doc wins and this module must be brought back into compliance.

import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';

export const CONFIG_VERSION = 1;
export const CONFIG_FILENAME = '.workflow-governance.json';

// Recognised CI providers. The workflow-setup skill maps detected
// .github/workflows/, .gitlab-ci.yml, etc. to these values. `other` is the
// escape hatch when the provider doesn't fit a category; `none` means the
// consumer hasn't picked one yet.
export const CI_PROVIDERS = Object.freeze([
  'github-actions',
  'gitlab-ci',
  'jenkins',
  'circleci',
  'buildkite',
  'azure-pipelines',
  'other',
  'none',
]);

// Recognised stack identifiers used by the setup skill. The list is
// advisory; the schema does not reject unknown values (an unrecognised
// stack name still validates so new ecosystems work without a kit update).
export const KNOWN_STACKS = Object.freeze([
  'node',
  'python',
  'rust',
  'go',
  'java',
  'kotlin',
  'csharp',
  'cpp',
  'swift',
  'ruby',
  'php',
  'perl',
  'elixir',
  'haskell',
  'zig',
  'lua',
  'shell',
  'mixed',
  'unknown',
]);

// Commands the kit's integration points read. All are optional — when a
// slot is unset, the relevant CLI verb falls back to its hardcoded default
// (currently npm-flavoured for backward compatibility during the v0.1.0
// transition; consumers run `/workflow-setup` to fill the slots).
export const COMMAND_SLOTS = Object.freeze(['guard', 'install', 'test', 'build', 'publish']);

// Hard cap on each command string. Prevents accidental shell-script-as-config
// blobs landing in the JSON. The setup skill keeps commands one-liners; if a
// consumer needs more, they wire a separate script and reference it here.
export const COMMAND_MAX = 512;

export class ConfigError extends Error {
  constructor(message, { code = 'config-error' } = {}) {
    super(message);
    this.name = 'ConfigError';
    this.code = code;
  }
}

export function emptyConfig() {
  return {
    version: CONFIG_VERSION,
    stack: { primary: 'unknown', detected: [] },
    commands: {},
    ci: { provider: 'none' },
  };
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function validateConfig(config) {
  if (!isPlainObject(config)) {
    throw new ConfigError('config must be an object');
  }
  if (config.version !== CONFIG_VERSION) {
    throw new ConfigError(
      `unknown config.version: ${JSON.stringify(config.version)} (expected ${CONFIG_VERSION}). Refusing to operate on an unrecognised schema; upgrade the kit or migrate the config.`,
      { code: 'unknown-version' },
    );
  }
  if (!isPlainObject(config.stack)) {
    throw new ConfigError('config.stack must be an object', { code: 'invalid-stack' });
  }
  if (typeof config.stack.primary !== 'string' || config.stack.primary.length === 0 || config.stack.primary.length > 64) {
    throw new ConfigError('config.stack.primary must be a non-empty string up to 64 chars', { code: 'invalid-stack-primary' });
  }
  if (!Array.isArray(config.stack.detected) || !config.stack.detected.every((s) => typeof s === 'string' && s.length > 0 && s.length <= 64)) {
    throw new ConfigError('config.stack.detected must be an array of non-empty strings (each <= 64 chars)', { code: 'invalid-stack-detected' });
  }
  if (new Set(config.stack.detected).size !== config.stack.detected.length) {
    throw new ConfigError('config.stack.detected contains duplicate entries', { code: 'duplicate-stack' });
  }
  if (!isPlainObject(config.commands)) {
    throw new ConfigError('config.commands must be an object', { code: 'invalid-commands' });
  }
  for (const [slot, value] of Object.entries(config.commands)) {
    if (!COMMAND_SLOTS.includes(slot)) {
      throw new ConfigError(`config.commands.${slot} is not a recognised slot (allowed: ${COMMAND_SLOTS.join(', ')})`, { code: 'unknown-command-slot' });
    }
    if (typeof value !== 'string') {
      throw new ConfigError(`config.commands.${slot} must be a string (got: ${typeof value})`, { code: 'invalid-command-type' });
    }
    if (value.length === 0) {
      throw new ConfigError(`config.commands.${slot} must be non-empty if present (omit the key to mark unset)`, { code: 'empty-command' });
    }
    if (value.length > COMMAND_MAX) {
      throw new ConfigError(`config.commands.${slot} exceeds ${COMMAND_MAX} chars; reference a separate script instead`, { code: 'command-too-long' });
    }
    if (/[\r\n]/.test(value)) {
      throw new ConfigError(`config.commands.${slot} must be a single-line command (no newlines)`, { code: 'multiline-command' });
    }
  }
  if (!isPlainObject(config.ci)) {
    throw new ConfigError('config.ci must be an object', { code: 'invalid-ci' });
  }
  if (!CI_PROVIDERS.includes(config.ci.provider)) {
    throw new ConfigError(
      `config.ci.provider must be one of ${CI_PROVIDERS.join(', ')} (got: ${JSON.stringify(config.ci.provider)})`,
      { code: 'invalid-ci-provider' },
    );
  }
}

// Resolves the configured command for a given slot, returning either the
// configured string or `null` when unset. Callers decide their own fallback
// (typically a hardcoded npm-flavoured default during v0.1.0 transition).
export function resolveCommand(config, slot) {
  if (!COMMAND_SLOTS.includes(slot)) {
    throw new ConfigError(`unknown command slot: ${slot}`, { code: 'unknown-slot' });
  }
  if (!config || !isPlainObject(config.commands)) return null;
  const value = config.commands[slot];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

// Normalised output: stable key order, 2-space indent, trailing newline,
// LF line endings. The setup skill's reproducibility regime relies on this
// — two valid runs against the same project + answers produce byte-identical
// files when serialized through writeConfig.
function normalize(config) {
  return {
    version: config.version,
    stack: {
      primary: config.stack.primary,
      detected: [...config.stack.detected].sort(),
    },
    commands: Object.fromEntries(
      COMMAND_SLOTS
        .filter((slot) => typeof config.commands[slot] === 'string' && config.commands[slot].length > 0)
        .map((slot) => [slot, config.commands[slot]]),
    ),
    ci: { provider: config.ci.provider },
  };
}

export function serializeConfig(config) {
  validateConfig(config);
  return `${JSON.stringify(normalize(config), null, 2)}\n`;
}

export function readConfig(filePath) {
  if (!existsSync(filePath)) return null;
  let raw;
  try {
    raw = readFileSync(filePath, 'utf8');
  } catch (err) {
    throw new ConfigError(`failed to read ${filePath}: ${err.message}`, { code: 'io-read' });
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new ConfigError(`failed to parse ${filePath}: ${err.message}`, { code: 'parse-error' });
  }
  validateConfig(parsed);
  return parsed;
}

export function writeConfig(filePath, config) {
  const json = serializeConfig(config);
  const dir = dirname(filePath);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const tmpPath = `${filePath}.tmp`;
  writeFileSync(tmpPath, json, 'utf8');
  try {
    renameSync(tmpPath, filePath);
  } catch (err) {
    // Cleanup the .tmp sibling on rename failure so a Windows EPERM
    // (which fires when the destination file is open in another
    // process) does not leave an orphan .tmp file behind. The original
    // filePath is never partially overwritten — POSIX rename is atomic
    // and the Windows two-step rename leaves the original intact on
    // failure.
    try {
      if (existsSync(tmpPath)) {
        // unlink via fs is sync; using rmSync(...,{force:true}) avoids
        // a second throw when the .tmp file vanished between the
        // existsSync check and the unlink call (e.g., concurrent CLI).
        unlinkSync(tmpPath);
      }
    } catch {
      // Swallow cleanup errors — the original failure is the meaningful
      // one and we want it to surface unchanged.
    }
    throw err;
  }
}

// Merge the agent's proposal into existing config preserving already-set
// fields per the §11 'config-as-source-of-truth' regime. Used by the
// workflow-setup skill on re-run: any field already populated in the file
// wins; only empty slots get filled. Cli callers use writeConfig directly.
export function mergePreservingExisting(existing, proposal) {
  if (!existing) return proposal;
  const result = emptyConfig();
  result.version = existing.version || proposal.version || CONFIG_VERSION;
  result.stack.primary = existing.stack?.primary && existing.stack.primary !== 'unknown'
    ? existing.stack.primary
    : proposal.stack?.primary || 'unknown';
  const detectedSet = new Set([
    ...(Array.isArray(existing.stack?.detected) ? existing.stack.detected : []),
    ...(Array.isArray(proposal.stack?.detected) ? proposal.stack.detected : []),
  ]);
  result.stack.detected = [...detectedSet];
  for (const slot of COMMAND_SLOTS) {
    const existingValue = existing.commands?.[slot];
    const proposalValue = proposal.commands?.[slot];
    if (typeof existingValue === 'string' && existingValue.length > 0) {
      result.commands[slot] = existingValue;
    } else if (typeof proposalValue === 'string' && proposalValue.length > 0) {
      result.commands[slot] = proposalValue;
    }
  }
  result.ci.provider = existing.ci?.provider && existing.ci.provider !== 'none'
    ? existing.ci.provider
    : proposal.ci?.provider || 'none';
  return result;
}
