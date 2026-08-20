---
name: workflow-uninstall
description: "Cleanly remove the workflow-governance kit from this project. Inverse of init/install-enforcement. Preserves user-modified content outside marker blocks. Opt-in for config and policy-doc purge."
---

# Workflow Uninstall

Use this skill when the user wants to remove the workflow-governance kit from the project. The kit covers a non-trivial surface (skills, hooks, scripts, settings entries, marker blocks); this skill walks through a safe, reversible removal.

## When NOT to use

- The user wants to upgrade the kit — use `init` with the new version instead.
- A lane is currently active and the user wants to "start over". Cancel the lane first via `workflow-close`; do NOT use `--purge-docs` mid-lane.
- The user has heavily customized kit-shipped files. The CLI's sha256 customization gate will preserve those automatically, but the user should be informed first.

## Procedure

1. Read the user's intent. Specifically confirm:
   - Are they removing the kit entirely, or just resetting one adapter?
   - Do they want to keep `.workflow-governance.json` (the per-project config)?
   - Do they want to keep `docs/WORKFLOW-GOVERNANCE.md` + `docs/CURRENT-PLAN.md` + `docs/HISTORY-MAP.md` + `docs/WORK-BACKLOG.md`?
2. Run the dry-run plan:

```sh
node bin/workflow-governance.mjs uninstall --check
```

3. Show the user the plan. Highlight:
   - Files to remove (with the kit-shipped vs customized split — customized files are preserved automatically).
   - `.claude/settings.json` and `package.json` un-merge ops (kit-injected entries removed, user entries preserved).
   - Marker block scrubs in `AGENTS.md` / `CLAUDE.md` (text outside markers preserved byte-identically).
4. If the user confirms, run:

```sh
node bin/workflow-governance.mjs uninstall --write
```

5. (Optional) If the user opts in to remove the config file:

```sh
node bin/workflow-governance.mjs uninstall --write --purge-config
```

6. (Optional, dangerous) If the user opts in to remove the four policy docs AND is not mid-lane:

```sh
node bin/workflow-governance.mjs uninstall --write --purge-docs
```

If the current plan is in ACTIVE state, the CLI refuses; the user must close the active lane first via `workflow-close`, or pass `--purge-docs-anyway-i-know-what-im-doing` to override (NOT recommended).

7. After `--write` succeeds, verify with `git status` and `git diff`. Commit the removal explicitly:

```sh
git add -A && git commit -m "chore: remove workflow-governance kit"
```

If anything looks wrong, `git checkout -- .` reverts everything (dirty-tree refusal guarantees this).

## Safety contract

- The CLI refuses to write if the working tree is dirty. The user must commit or stash first so git is the recovery path.
- Customized files (sha256 mismatch vs shipped templates) are PRESERVED with a diagnostic. The user can delete those manually if they truly want.
- Marker-block scrubs only touch content between `<!-- WORKFLOW-GOVERNANCE:START -->` and `<!-- WORKFLOW-GOVERNANCE:END -->`. Text outside markers is byte-identical post-scrub.
- The `--purge-docs` flag has an extra refusal layer for active-lane state.

## Output Contract

Show the user the dry-run plan before any write. Report which files were preserved (customized) and which were removed. Never claim "done" without running the dry-run plan first.
