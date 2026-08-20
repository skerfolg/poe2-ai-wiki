---
name: Workflow governance priority
description: Before any code or structural change, read docs/CURRENT-PLAN.md first; per-agent runtime notes (.omc/plans, .omx/plans, .codex/plans, .claude/local) are not active control; invoke the workflow-* skills at the right triggers.
type: feedback
---

> **Canonical source:** `.agent-context/workflow-governance-priority.md` (git-tracked, runtime-neutral, readable by every agent). This memory file is a Claude-formatted snapshot of that canonical content. If the two diverge, the `.agent-context/` file wins and this snapshot must be re-synced.

Every implementation or closure session in a project that uses the Workflow Governance Kit must follow the kit's governance procedure before touching code, tooling, or governance documents.

**Why:**
This memory exists because governance bypasses are easy to commit accidentally. A representative incident: an agent skipped the governance entry-check, ran a prework series across multiple commits without reading `docs/CURRENT-PLAN.md`, treated a backlog item as if it were the active lane, attached a version label up front, branched from a non-default base without an Integration Branch Override entry, never updated the Mermaid status graph in lockstep, and treated `.omc/plans/*` as active control. The violation was discovered only when the user pointed it out by hand. The kit's enforcement directives — and this memory — exist so future agents do not repeat that pattern.

**How to apply:**

1. **Before any implementation, refactor, or closure work:**
   - Invoke the `workflow-status` skill, or run `npm run workflow:status`.
   - Read `docs/CURRENT-PLAN.md` and confirm the active lane matches the work the agent is about to do.
   - If the intended work is not the active lane, ask the user to promote the corresponding `WORK-BACKLOG.md` item (or the relevant planning artifact) into `CURRENT-PLAN.md` before proceeding.

2. **Absolute prohibitions (BLOCKING):**
   - Do not treat `.omc/plans/`, `.omx/plans/`, `.codex/plans/`, `.claude/local/`, scratch files, or session transcripts as active control. They are historical reference only and become active only if `CURRENT-PLAN.md` explicitly reactivates a specific document.
   - Do not attach a release/version label (e.g., `v1.0.0`) to a lane up front. Version labels are assigned at release composition via the `workflow-release` skill.
   - Do not commit code or tooling changes without updating `docs/CURRENT-PLAN.md` (text + Mermaid status graph) in the same commit. The universal `.githooks/pre-commit` gate enforces this rule for every agent and every plain terminal commit; bypassing it with `git commit --no-verify` is a governance violation regardless of whether a hook catches it.
   - Do not equate the act of writing artifacts, evidence, or summaries with governance compliance. Compliance is the Current Plan update + History Map update for closures + `npm run workflow:guard` pass.

3. **At task / phase / slice / lane / milestone closure:**
   - Invoke the `workflow-close` skill.
   - Update `docs/CURRENT-PLAN.md` text and the Mermaid status graph in lockstep (per `WORKFLOW-GOVERNANCE.md` §4 — Visual Status Views).
   - Classify cleanup candidates and resolve git/worktree hygiene.

4. **At release / version composition:**
   - Invoke the `workflow-release` skill.
   - Assign the version label only at this point; update `docs/HISTORY-MAP.md` with the new version entry and a `Composed milestones:` line per `WORKFLOW-GOVERNANCE.md` §3.

5. **Default integration branch:**
   - Branch feature work from the integration branch named in `docs/CURRENT-PLAN.md` (typically `main`, sometimes `develop`, sometimes a release branch).
   - If the active lane requires a non-default base, the lane must record an Integration Branch Override entry (`WORKFLOW-GOVERNANCE.md` §8) before any branching happens.

6. **Skill priority on conflict:**
   - The workflow-* skills (`workflow-status`, `workflow-init`, `workflow-close`, `workflow-release`) are governance-level and win over orchestration, planning, autopilot, RAL-style loops, and code-review skill systems.
   - Run other skill systems only after `workflow-status` has confirmed the active lane is aligned with the intended work.

**Canonical documents to keep in mind:**

- `docs/WORKFLOW-GOVERNANCE.md` — full policy.
- `docs/CURRENT-PLAN.md` — active lane (read before any code change).
- `docs/HISTORY-MAP.md` — release/version index; release-composed entries only.
- `docs/WORK-BACKLOG.md` — version-unassigned candidate work.
- The project's canonical charter or product-governance document (positioning, non-goals, verification law).

**Convenience commands (when the kit is installed and `package.json` has the workflow scripts):** `workflow:status`, `workflow:guard`, `workflow:mermaid`, `workflow:cleanup`.
