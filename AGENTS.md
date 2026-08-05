# PoE2 AI Wiki — 에이전트 지침 (지도)

PoE2 지식 **엔진** + Claude/Codex용 **MCP 도구·스킬**. 웹서비스 아님.
**단일 진실 소스**: [docs/BLUEPRINT.md](docs/BLUEPRINT.md)(방향·결정) · [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)(구조).

## KB 질의는 MCP 도구로 (파일 탐색 금지)

**PoE2 게임 지식 질문("~에 좋은 노드/모드/아이템은?")은 `pok` MCP 도구로 답한다:**
`search_kb`(키워드는 게임 용어로 — 예: "생명력 증가" type=Passive) → `get_entry`(fields 선별) → `related`(관계 순회).
`knowledge/` NDJSON·`external/pob`를 Grep/Read로 뒤지지 말 것 — 16,000+ 레코드를 파일로 탐색하면
수 분·수천 토큰이 들지만 search_kb는 1콜이다 (실측 2026-07-30: 파일 탐색 7분 vs 도구 1초).
파일 직접 접근은 ingest 개발·검증 작업에만.

**"무엇이 어떤 형태로 있나"는 `describe_kb`·`describe_type`으로.** 레코드를 찾는 게 아니라
필드 충전율·값 분포를 훑는 질문에는 `search_kb`가 답하지 못하고, `schema/*.schema.json`은
**정의**라서 실제 채워진 정도와 다르다. 도구 경로가 없어 파일 탐색으로 도피한 사례가 4회
반복됐다(B-11). 예: Skill의 `category`는 12.5%만 채워져 있어 그것으로 거르면 대부분을 놓친다.

**`search_kb`가 0건이면 결과에 진단(`empty`/`why`)이 함께 온다 — 그것부터 읽는다.**
빈 결과가 곧 "KB에 없다"는 아니다. 실측 2026-08-05: 빈 결과 9건이 전부 질의 방식 문제였다
(효과 문구 한글 미수록 · `type` 오해 — 룬은 `Item`이 아니라 `Modifier` · 다단어 AND 과협소).
**효과 문구의 한글 보유율은 타입마다 다르다**: Passive 99.6%지만 Skill 0.2%·Support 0%이므로
스킬·보조를 효과로 찾을 땐 영어 표기를 쓴다.

## 철칙 (항상 적용)

1. ⛔ **구조 임의 변경 금지** — 디렉터리 구성·모듈 경계·저장 위치·의존 방향 변경은 **반드시 사용자와 상호협의 후에만**. (기존 모듈 안에 파일 추가는 허용, 새 최상위 폴더·경계 이동은 합의 필요.)
2. **정본 vs 파생** — `knowledge/`=git 정본(진실). `var/`·`artifacts/`·`external/`=gitignore. 파생을 진실로 취급 금지.
3. **엔진=결정적** — `src/pok/engine/`엔 빌드 솔버·생성 판단을 넣지 않는다. 판단은 `skills/`+에이전트.
4. **인덱스는 코드가 자동 재생성** — `var/index.sqlite`를 손대거나 커밋하지 말 것. `src/pok/index/`의 self-healing이 처리(없음/KB수정/버전업 감지).

## 협업 규율 (여러 세션이 동시에 돈다)

1. **main 직접 커밋 금지** — 브랜치에서 작업 후 PR.
2. ⚠️ **머지 후 로컬 `main`을 반드시 당긴다** — **원격 머지와 로컬 갱신은 다르다.**
   PR을 머지해도 로컬 `main`은 그대로이고, 그걸 쓰는 세션은 **옛 코드로 작업한다**.
   ```bash
   git -C <레포 루트> pull --ff-only
   ```
   실측 사고(2026-08-05): PR 4개(#16~#19)가 원격에 머지됐는데 로컬 `main`이 #15에
   멈춰 있었고, 그 상태로 빌드 테스트가 돌아 **규율 개정 6건·도구 수정 4건이 전부
   미적용**이었다 — 측정하려던 것을 측정하지 못했다.
3. **작업 시작 전 최신 여부를 확인한다** — `git fetch && git log HEAD..origin/main`.
   비어 있지 않으면 먼저 당긴다. 특히 **다른 세션의 결과를 이어받을 때**.
4. **PR을 올린 세션이 머지 후 동기화까지 책임진다** — 머지는 사용자가, 당기는 것은
   세션이. 그래야 "누가 하겠지"로 빠지지 않는다.

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
