# Work Backlog

**Status**: Version-unassigned work registry
**Policy**: [Workflow Governance](WORKFLOW-GOVERNANCE.md)
**Current control**: [CURRENT-PLAN.md](CURRENT-PLAN.md)

This file records work that is intentionally not assigned to a release version yet. Version numbers are assigned later, when completed work is composed into a release via the `workflow-release` skill.

## Backlog Rules

- Do not implement a backlog item from this file alone.
- Backlog items are not version commitments.
- To start work, select one backlog item, create or update a concrete plan/test-spec pair (or the project's equivalent planning artifact), and promote that selected item into `CURRENT-PLAN.md`.
- After one or more items are completed, decide the release/version label during release composition (see `WORKFLOW-GOVERNANCE.md` §7 — Version Closure, and §3 — Composed Milestones Convention).
- Honor any product-boundary rules from the canonical charter or product-governance document; the backlog does not override charter constraints.

## Queue

| Item | Status | Activation gate | Current disposition |
| --- | --- | --- | --- |
| (none yet) | — | — | Add candidate lanes here when they are identified. |

### Status Vocabulary

| Status | Meaning |
| --- | --- |
| `unstarted` | Identified as a candidate lane; no implementation yet. |
| `active` | Promoted to `CURRENT-PLAN.md`; remains as a backlog history pointer until closed. |
| `waiting / blocked` | Cannot start until a stated gate clears (external dependency, prior lane closure, etc.). |
| `superseded` | Replaced by a different lane; keep the entry only if useful as historical context, otherwise remove. |

## Backlog Items

Each candidate lane gets its own subsection below the Queue table. Use the shape illustrated by the example. Remove the example before adding real items.

### Example: BI-feature-x

> Remove this example once the first real backlog item is added.

Status: `unstarted`

Purpose:
- One sentence describing the user-visible outcome the lane is meant to achieve.

Scope seed:
- Bullet list of intended scope items, kept compact.

Out-of-scope (tracked separately):
- Items that look related but belong to a different lane. Name the destination lane (e.g., `BI-feature-y`) when known.

Non-scope:
- Items that explicitly will not be addressed in this lane regardless of timing (e.g., charter-prohibited capabilities).

Expected planning inputs:
- Pointers to source planning artifacts, design docs, customer requests, or charter sections that motivate the lane.

## Current Notes

- Replace this template's example items with real candidate lanes as they are identified.
- Keep this file focused on candidate lanes; once a lane is active, its detailed phases live in `CURRENT-PLAN.md`, not here.
