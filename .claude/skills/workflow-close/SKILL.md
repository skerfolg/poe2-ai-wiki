---
name: workflow-close
description: "Close a work item by updating Current Plan, release-composed History Map entries when applicable, Mermaid graphs, cleanup candidates, and git/worktree hygiene"
---

# Workflow Close

Use this skill when a task, slice, lane, milestone, or version is being closed.

## Procedure

1. Identify the closure level:
   - task
   - phase
   - slice
   - lane
   - milestone
   - version
2. Update `docs/CURRENT-PLAN.md`:
   - active lane/slice if it changed
   - text status
   - evidence
   - immediate next work
   - Mermaid status graph (in the same edit as the text status)
   - cleanup/worktree/branch disposition when it affects current work
   - remove completed-lane details that no longer control active work and point to artifacts instead

   **Canonical Next Step transition — REQUIRED:**

   After closure, set the new Canonical Next Step in `## Canonical Next Step` from the first un-closed Baseline row (per `docs/WORKFLOW-GOVERNANCE.md` §13.2 — Baseline Structure matching algorithm). If the closed item WAS the canonical step (i.e., the previous `## Canonical Next Step` body named the now-closed identity), this transition is **REQUIRED** in the closure commit — not SHOULD, not RECOMMENDED. The commit MUST include both the closed-item status change and the new Canonical Next Step directive in the same diff.

   The transition rule is binding because:
   - Leaving the prior canonical step in `## Canonical Next Step` after closure causes downstream agents to act on stale direction (BI-kit-lifecycle v0.1.4 L1 incident root cause; see `docs/WORKFLOW-GOVERNANCE.md` §13.3).
   - The Phase 3 schema guard (`scripts/workflow-guard.mjs` via `validateCurrentPlan`) emits a WARNING when Canonical Next Step does not match the first unclosed Baseline row; deliberate overrides require an Open Decisions row naming the mismatch.
   - This is the root-cause-fixing procedural rule from the BI-kit-lifecycle deep-interview Round 5 spec.
3. If the closure completes work that is not yet release-composed, archive closure evidence under the project's artifact directory (for example `artifacts/20-milestones/<lane>/`) and point `docs/CURRENT-PLAN.md` to that artifact instead of writing the summary into `docs/HISTORY-MAP.md`.
4. If the closure is a release-composition or version closure, update `docs/HISTORY-MAP.md`:
   - compact summary only
   - include the `Composed milestones:` line listing every closed lane absorbed into the version (per `WORKFLOW-GOVERNANCE.md` §3 — Composed Milestones Convention)
   - update the Mermaid timeline graph if status changed
   - release/version entries only; no active workflow state, backlog items, or unversioned completed workflow summaries
5. Run:

```sh
npm run workflow:guard
```

6. Classify cleanup candidates:
   - preserve as source/config/fixture/evidence
   - move to artifact/evidence directory
   - delete as temporary data
   - defer with owner/status note
7. For git/worktree cleanup:
   - confirm the target integration branch (default per `CURRENT-PLAN.md`; honor any active Integration Branch Override)
   - confirm the branch is merged before deletion
   - delete temporary worktrees and branches only when explicitly approved or already clearly requested

## Safety

- Hooks and guards must not auto-edit governance documents.
- Destructive cleanup remains approval-gated unless the user explicitly requested the exact cleanup.
- Never hide a `PARTIAL`, `FAIL`, or `NOT STARTED` status to make the graph look complete.
- Do not close a task while `docs/CURRENT-PLAN.md` still describes a stale previous lane as active.
- Do not write lane, milestone, or backlog closure details into `HISTORY-MAP.md` until completed work has been composed into a release/version bundle.
