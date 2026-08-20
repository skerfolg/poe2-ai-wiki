---
name: workflow-close
description: "Close a work item by updating Current Plan, History Map, Mermaid graphs, cleanup candidates, and git/worktree hygiene"
---

# Workflow Close

Use this skill when a task, slice, lane, milestone, or version is being closed.

Procedure:

1. Update `docs/CURRENT-PLAN.md` status, evidence, next work, and Mermaid graph.

   **Canonical Next Step transition — REQUIRED:** After closure, set the new Canonical Next Step from the first un-closed Baseline row (per WORKFLOW-GOVERNANCE.md §13.2 baseline matching). If the closed item WAS the canonical step, this transition is **REQUIRED** in the closure commit — not SHOULD. The commit MUST include both the closed-item status change and the new Canonical Next Step directive in the same diff. (Drift-incident root-cause fix per §13.3.)
2. Update `docs/HISTORY-MAP.md` only for durable version/lane outcomes.
3. Classify cleanup candidates.
4. Run:

```sh
npm run workflow:guard
```

Hooks and guards must not auto-edit governance documents.
