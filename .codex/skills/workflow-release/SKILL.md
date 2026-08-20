---
name: workflow-release
description: "Interactive wrapper around `npx workflow-governance release compose --write` that composes already-closed lanes into a versioned release entry. Use when you have one or more closed lanes that should become a named release (npm version bump, HISTORY-MAP entry, CHANGELOG section). Delegates the atomic mutation of HISTORY-MAP.md + CURRENT-PLAN.md + package.json to the CLI; the skill drives the operator dialogue and the pre/post-compose checklist."
---

# Workflow Release

Use this skill when one or more closed lanes are ready to become a named release. The skill drives the operator dialogue; the actual mutation of `docs/HISTORY-MAP.md` + `docs/CURRENT-PLAN.md` + `package.json` is performed atomically by the `release compose --write` CLI. Do not edit those three files by hand — that path is reserved for the CLI and bypassing it risks a partially-composed working tree.

This skill does NOT close individual lanes. Run `/workflow-close` for each lane first; only then is it eligible for release composition. The CLI rejects empty plans by default (`--allow-empty` exists but is for the rare same-version pre-release-to-release promotion).

## Procedure

### Step 1 — Inventory

Read the inputs the CLI will consume:

- `docs/HISTORY-MAP.md` — every closed lane is registered here. The `## Closed Lanes — Unreleased Evidence` section (or equivalent bullets) is what `release compose` scans.
- `docs/CURRENT-PLAN.md` — active lane and recent Open Decisions. Closed lanes that are about to be release-composed should have their per-sub-task detail still here; the CLI moves it into HISTORY-MAP and trims it from CURRENT-PLAN in one pass.
- `package.json` — current version (the CLI will bump this in lockstep).
- The `artifacts/20-milestones/*/closure-archive-*.md` files for each lane being composed, so you can summarise their outcomes in the version's CHANGELOG entry.

Run the preview:

```sh
npx workflow-governance release compose --check
```

This prints the plan summary (previous version, next version, lanes absorbed, files to mutate) without writing anything. Use it to confirm the lane set matches your expectation.

### Step 2 — Decide the version

`release compose` accepts either form:

- `--version 0.1.1` — explicit version. Use when you have a target version in mind (most patch / minor releases).
- `--bump major|minor|patch` — semver bump from `package.json` version. Use for routine bumps without a specific target.

Semver discipline (per `docs/WORKFLOW-GOVERNANCE.md` §7.2):
- Pre-1.0 (kit's current state): `patch` for fixes / non-breaking additions; `minor` for breaking changes.
- Post-1.0: standard semver — `major` for breaking, `minor` for additions, `patch` for fixes.

If unsure, ask the user. Do not bump major without explicit confirmation.

### Step 3 — Migrate CHANGELOG

`CHANGELOG.md` uses [Keep a Changelog](https://keepachangelog.com/) format. The `release compose` CLI does NOT migrate the `[Unreleased]` heading automatically (deferred Tier 4 follow-up). Do it by hand BEFORE running `--write`:

1. Read the current `[Unreleased]` section.
2. Rename its heading to `[X.Y.Z] - YYYY-MM-DD` where X.Y.Z is the target version and YYYY-MM-DD is today's date.
3. Insert a new empty `[Unreleased]` section above it (preserve the `### Added` / `### Changed` / `### Fixed` subheading scaffolding for the next cycle).
4. If the `[Unreleased]` section has no entries, populate it from the closure archives of the lanes being composed before renaming.

Commit the CHANGELOG migration in the same commit as the `release compose --write` mutation (it is one atomic version-bump unit).

### Step 4 — Preview again with explicit version

After the CHANGELOG migration is staged but before `--write`, run the check one more time:

```sh
npx workflow-governance release compose --version X.Y.Z --check
```

Confirm the plan summary lists the right lanes, the right files to mutate, and zero `warning:` diagnostics. If the diagnostics list is non-empty, fix the underlying issue (a malformed bullet in HISTORY-MAP, a missing closure archive, a misnamed lane) before proceeding.

### Step 5 — Compose with `--write`

```sh
npx workflow-governance release compose --version X.Y.Z --write
```

The CLI:
- writes `docs/HISTORY-MAP.md`, `docs/CURRENT-PLAN.md`, and `package.json` atomically via `.tmp` siblings + rename;
- runs `npm run workflow:guard` automatically after the rename and exits non-zero if the gate fails;
- prints `release compose: wrote v<X.Y.Z> and guard passed. Commit the diff, tag v<X.Y.Z>, and push.`

If the guard fails, the mutations are on disk — review the diff with `git diff` and either fix forward or `git restore` to back out.

### Step 6 — Commit, tag, push

In one commit:

```sh
git add docs/HISTORY-MAP.md docs/CURRENT-PLAN.md package.json CHANGELOG.md
git commit -m "chore(release): v<X.Y.Z>"
git push origin main
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

Push the branch BEFORE the tag. A tag arriving on the remote ahead of its commit on the default branch makes CI dispatch on the tag find no source.

### Step 7 — Publish hand-off

Publishing to a registry (npm, GitHub Releases) is a user-executed step in a fresh shell with the user's own credentials. The agent's responsibility ends at the tag push. Direct the user to:

```powershell
# In a fresh PowerShell with $env:NPM_TOKEN set (use a single-use Granular Access Token)
scripts\publish.ps1 -Version X.Y.Z
```

Or, if the consumer does not ship the helper script:

```sh
NPM_TOKEN=<single-use-token> npx workflow-governance release publish --write
```

Do NOT execute the publish step from inside the skill — the agent has no access to the user's credentials and storing them in the conversation transcript is a leak vector.

## Safety

- The `release compose --write` CLI is the only sanctioned mutation path for HISTORY-MAP + CURRENT-PLAN + package.json under a release. Bypassing it (hand-editing any of the three) risks a partially-composed working tree if the edit fails mid-way.
- Do not assign a version label before the closed-lane set is known. Version is decided by the plan, not asserted before it.
- Do not include unstarted backlog items, active lanes, or lanes whose `/workflow-close` is still pending.
- Do not write raw evidence, phase logs, or transcripts into HISTORY-MAP. The CLI emits compact one-line entries + a `Composed milestones:` line; that is the contract.
- Do not tag, push, or publish without explicit operator confirmation. The skill drives the dialogue; the operator presses the buttons.
- Do not store NPM_TOKEN or any registry credential in any agent-authored file, commit message, or memory entry. The token is the operator's; the agent never sees it.
