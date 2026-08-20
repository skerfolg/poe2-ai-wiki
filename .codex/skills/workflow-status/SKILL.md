---
name: workflow-status
description: "Inspect workflow governance status, current plan, history map, git/worktree hygiene, and Mermaid consistency"
---

# Workflow Status

Use this skill when the user asks where the project stands, how much work remains, or whether workflow governance is being followed.

Run:

```sh
npm run workflow:status
```

**Surface `## Canonical Next Step` FIRST in the report** — it is the single bolded directive naming the exact next executable action for the active lane. Lead with it. Only after that, list the supporting context: active lane identifier, phase/slice statuses, Deferred Candidates (clearly labeled as NOT the next step), Mermaid/text consistency, worktree/branch hygiene, and cleanup candidates.

Drift prevention (WORKFLOW-GOVERNANCE.md §13.3): listing deferred candidates or summaries before the Canonical Next Step caused the BI-kit-lifecycle v0.1.4 L1 incident. Canonical-Next-Step-FIRST ordering is REQUIRED.
