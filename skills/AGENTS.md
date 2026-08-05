# skills/ — 고수준 워크플로 (생성 파이프라인 오케스트레이션)

- 각 스킬 = `SKILL.md`(Claude) + `AGENTS.md`(Codex). 둘은 **같은 MCP 도구**를 호출한다.
  - ⚠️ **`SKILL.md`는 `.claude/skills/<이름>/`에 둔다** — 여기(`skills/<이름>/`)가 아니다.
    Claude Code가 탐색하는 경로는 `.claude/skills/<이름>/SKILL.md`(프로젝트)와
    `~/.claude/skills/<이름>/SKILL.md`(개인) **둘뿐**이라, 이 디렉터리에 두면 `/스킬명`이
    뜨지 않는다. 실측 2026-08-05(공식 문서 확인): frontmatter를 갖춰 놓고도 위치가
    달라 두 스킬 모두 슬래시 호출이 불가능했다.
  - `SKILL.md`에는 **frontmatter(`name`·`description`)가 있어야** 한다. 없으면
    `Unknown skill`로 실패한다(실측 2026-08-04).
  - 지침 본문은 **`AGENTS.md` 한 벌만** 둔다 — 이 디렉터리가 그 자리다. `SKILL.md`는
    진입점(frontmatter + 시작 전 확인사항)이고 규율을 복사하지 않는다. 두 벌이 되면 어긋난다.
- **"무엇을 만들지"의 판단·순서가 여기 산다** — 엔진(`src/pok/engine/`)은 결정적 도구만 제공(AD-3).
- 생성 파이프라인(BLUEPRINT §10.2)의 오케스트레이션은 엔진이 아니라 스킬의 몫.
- 상세: [PROJECT_STRUCTURE](../docs/PROJECT_STRUCTURE.md) §1 · [BLUEPRINT](../docs/BLUEPRINT.md) §10
