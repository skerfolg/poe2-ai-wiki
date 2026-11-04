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

### BI-search-revision

**Purpose**: 생성·탐색 접근 개선과 실제 품질 평가.
**Status**: active — 사용자 2026-11-05 goal 실행 승인.
**Sub-tasks**: S1 기존 표현 검증 → S2 평가 동결 → S3 판단4회 → S4 조건부 발견4회 → S5 확인된 병목 수정 → S6 채택 판단/사용자 검토.
**Budget**: 시험당45분, 총8회/6시간 이내. 임의 재시도 금지.

### 이전 진행 기록 보존

기존 CURRENT-PLAN의 M5/R0–R7 혼재 기록은 [원문](POK_SEARCH_PREVIOUS_PLAN.md)에 보존했다. #188 품질 미입증과 UI 별도 작업은 완료 처리하지 않는다. 새 lane 활성화는 사용자의 구체 goal 지시를 따른다.
