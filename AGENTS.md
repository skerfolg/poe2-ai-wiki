# PoE2 AI Wiki — 에이전트 지침 (지도)

PoE2 지식 **엔진** + Claude/Codex용 **MCP 도구·스킬**. 웹서비스 아님.
**단일 진실 소스**: [docs/BLUEPRINT.md](docs/BLUEPRINT.md)(방향·결정) · [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)(구조).

## KB 질의는 MCP 도구로 (파일 탐색 금지)

**PoE2 게임 지식 질문("~에 좋은 노드/모드/아이템은?")은 `pok` MCP 도구로 답한다:**
`search_kb`(키워드는 게임 용어로 — 예: "생명력 증가" type=Passive) → `get_entry`(fields 선별) → `related`(관계 순회).
`knowledge/` NDJSON·`external/pob`를 Grep/Read로 뒤지지 말 것 — 16,000+ 레코드를 파일로 탐색하면
수 분·수천 토큰이 들지만 search_kb는 1콜이다 (실측 2026-07-30: 파일 탐색 7분 vs 도구 1초).
파일 직접 접근은 ingest 개발·검증 작업에만.

## 철칙 (항상 적용)

1. ⛔ **구조 임의 변경 금지** — 디렉터리 구성·모듈 경계·저장 위치·의존 방향 변경은 **반드시 사용자와 상호협의 후에만**. (기존 모듈 안에 파일 추가는 허용, 새 최상위 폴더·경계 이동은 합의 필요.)
2. **정본 vs 파생** — `knowledge/`=git 정본(진실). `var/`·`artifacts/`·`external/`=gitignore. 파생을 진실로 취급 금지.
3. **엔진=결정적** — `src/pok/engine/`엔 빌드 솔버·생성 판단을 넣지 않는다. 판단은 `skills/`+에이전트.
4. **인덱스는 코드가 자동 재생성** — `var/index.sqlite`를 손대거나 커밋하지 말 것. `src/pok/index/`의 self-healing이 처리(없음/KB수정/버전업 감지).

## 적재적소 — 언제 무엇을 읽나

- 구조·경계·저장 위치 관련 작업 → **docs/PROJECT_STRUCTURE.md**
- 방향·결정 배경(D1~D24) → **docs/BLUEPRINT.md**
- KB 레코드·스키마·조건·관계 작업 → **docs/KB_DATA_MODEL.md** (KD-1~4 확정)
- KB 수집·정형화·원시 스냅샷·완전성 기준 → **docs/KB_INGEST.md** (KI-1~7 확정)
- 지금 어느 단계인지·다음 할 일 → **docs/ROADMAP.md**
- 실전 빌드 테스트를 수행한다 → **docs/BUILD_TEST_PROTOCOL.md** (무개입 규칙·기록 항목) (P0~P6, Exit 기준. 단계 건너뛰기 금지)
- 특정 모듈 작업 → 그 디렉터리의 **AGENTS.md** (자동 로드됨)
- MCP 도구 추가 → docs/PROJECT_STRUCTURE.md §4(의존 방향)·§7, `src/pok/mcp/AGENTS.md`

## 스택 (요약)

Python 3.12+ · FastMCP · git 텍스트 정본 + SQLite(FTS5) 인덱스 · PoB(LuaJIT, headless) 계산 오라클 · Windows+macOS.
