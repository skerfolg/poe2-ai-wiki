#!/usr/bin/env node
// Workflow Governance Kit — pre-commit command resolver.
//
// Reads .workflow-governance.json via the canonical config-schema.mjs
// validator and prints the resolved value of a single commands.<slot>
// to stdout. Used by .githooks/pre-commit Stage 2 to look up
// commands.guard without bypassing the schema invariant.
//
// Exit codes:
//   0  resolved command written to stdout (or empty string when slot is unset
//      in an otherwise valid config — caller treats empty as "use kit default")
//   2  .workflow-governance.json not present (caller falls back to defaults)
//   1  .workflow-governance.json present but invalid; nothing written to stdout

import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { ConfigError, readConfig, resolveCommand } from './lib/config-schema.mjs';

const slot = process.argv[2];
if (!slot) {
  process.stderr.write('workflow-resolve-command: missing slot argument\n');
  process.exit(1);
}

const configPath = resolve(process.cwd(), '.workflow-governance.json');
if (!existsSync(configPath)) {
  process.exit(2);
}

try {
  const cfg = readConfig(configPath);
  if (!cfg) {
    process.exit(2);
  }
  const command = resolveCommand(cfg, slot);
  if (command) {
    process.stdout.write(command);
  }
  process.exit(0);
} catch (err) {
  if (err instanceof ConfigError) {
    process.stderr.write(`workflow-resolve-command: ${err.message} [${err.code}]\n`);
  } else {
    process.stderr.write(`workflow-resolve-command: ${err.message}\n`);
  }
  process.exit(1);
}
