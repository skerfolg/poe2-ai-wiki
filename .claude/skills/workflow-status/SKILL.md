---
name: workflow-status
description: "Inspect workflow governance status, current plan, history map, git/worktree hygiene, and Mermaid consistency"
---

# Workflow Status

Use this skill when the user asks where the project stands, how much work remains, or whether workflow governance is being followed.

## Procedure

1. Read:
   - `docs/WORKFLOW-GOVERNANCE.md`
   - `docs/CURRENT-PLAN.md`
   - `docs/HISTORY-MAP.md`
   - `docs/WORK-BACKLOG.md`
   - `AGENTS.md`
   - `CLAUDE.md`

2. **Surface `## Canonical Next Step` FIRST in the report.** This is the most important line — the single bolded directive that names the exact next executable action for the active lane. Lead the report with it. Every consumer of `workflow-status` MUST be able to read the next-action directive in the first lines of the output without scrolling.

   Run:

   ```sh
   npm run workflow:status
   ```

3. **Then** list the supporting context (in this order, after the Canonical Next Step is stated):
   - active lane identifier
   - current phase/slice statuses
   - **Deferred Candidates** (clearly labeled as NOT the next step — supporting context only)
   - whether the Current Plan is focused on the current active lane rather than completed work
   - whether the History Map contains only release/version history and not active workflow or backlog state
   - whether version-unassigned work is kept in the Work Backlog
   - Mermaid/text status consistency issues
   - stale worktree/branch candidates
   - temporary file/document cleanup candidates
   - any missing Current Plan update required by the latest task/change

## Output Contract

Keep the answer concise. Separate evidence from inference. Do not mark work complete unless the guard output and relevant tests support it.

**Drift prevention** (per `docs/WORKFLOW-GOVERNANCE.md` §13.3): the Canonical Next Step IS the active lane's single immediate next executable directive. Listing deferred candidates or status summaries BEFORE the Canonical Next Step caused the v0.1.4 BI-kit-lifecycle lane's L1 incident: an agent picked a task from `## Deferred Candidates` instead of acting on `## Canonical Next Step`. The Canonical-Next-Step-FIRST ordering above is the root-cause fix and is REQUIRED for every workflow-status invocation.
