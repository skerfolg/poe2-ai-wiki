---
name: workflow-doctor
description: "Diagnose workflow-governance kit install health (9 checks across config, docs, hooks, skills, package.json, marker blocks, and live-doc schema). `--fix` auto-repairs safe deterministic cases."
---

# Workflow Doctor

Use this skill when the user wants to verify their workflow-governance kit install is healthy, or when other kit commands behave unexpectedly and you suspect a configuration drift.

## When to use

- After upgrading the kit and before any other operation.
- When `workflow-governance` commands behave unexpectedly (missing files, hook not firing, etc.).
- Before opening a support issue — doctor's output is the diagnostic report.

## When NOT to use

- For per-commit gating — use `workflow-governance guard` instead (doctor is one-shot).
- For repairing structured governance docs (CURRENT-PLAN.md / HISTORY-MAP.md schema violations) — use `workflow-governance migrate-docs` instead.

## Procedure

1. Run the dry-run check:

```sh
node bin/workflow-governance.mjs doctor --check
```

2. Read the report. Findings are grouped by severity:
   - **errors**: must fix manually (e.g., missing required governance docs → reinstall the kit).
   - **warnings**: most can be auto-repaired via `--fix`. Some require manual review (e.g., customized files, inherited git config values).
   - **info**: ambient state; no action needed.

3. If the report has fixable findings, run:

```sh
node bin/workflow-governance.mjs doctor --fix
```

This applies only safe deterministic repairs:
- `git config --local core.hooksPath .githooks` (only when both local AND inherited values are unset).
- `rm -rf` orphan v0.1.0-era directories (only when content matches the v0.1.0 allowlist).
- `npm pkg fix` to canonicalize `package.json` bin field (skipped if npm is not on PATH).

4. For findings that are NOT fixable, follow the remediation pointer in each finding's message.

## Safety contract

- `--check` is read-only; it never mutates anything.
- `--fix` only applies repairs marked `fixable: true` in the planDoctor output. The library has explicit gates:
  - C4 (git config core.hooksPath): refuses to overwrite when an inherited non-default value exists (e.g., corporate compliance hooks). Manual remediation required.
  - C6 (orphan v0.1.0 directories): refuses to remove when content does NOT match the v0.1.0 allowlist (sha256 gate; protects user-customized content).
  - C7 (`npm pkg fix`): probes `npm --version` first; if npm is unavailable, emits a warning with manual instructions instead of throwing.
- `--fix` does NOT require a clean tree (unlike `cleanup-plan` / `uninstall`). The repairs are git-recoverable (`git checkout -- package.json` if needed), and requiring a clean tree creates a chicken-and-egg problem for broken installs.

## Output Contract

Show the user the per-severity grouped report. Highlight which findings are fixable. Never claim "healthy" without running `--check` first.
